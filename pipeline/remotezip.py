"""Read individual members of a remote ZIP via HTTP Range requests.

The police archive is 1.62 GiB but our 12-month window of street CSVs is only
~580 MB of it, so we fetch the central directory once and then stream just the
members we need. Stdlib struct/zlib only; httpx for transport.
"""
from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass

import httpx

EOCD_SIG = 0x06054B50
ZIP64_LOCATOR_SIG = 0x07064B50
ZIP64_EOCD_SIG = 0x06064B50
CD_ENTRY_SIG = 0x02014B50
LOCAL_HEADER_SIG = 0x04034B50

EOCD_TAIL_FETCH = 128 * 1024  # generous: EOCD + comment + zip64 records


@dataclass
class Member:
    filename: str
    method: int          # 0 = stored, 8 = deflate
    comp_size: int
    uncomp_size: int
    header_offset: int


class RemoteZip:
    def __init__(self, url: str, max_retries: int = 4):
        self.max_retries = max_retries
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(180, connect=30),
            headers={"User-Agent": "uk-crime-heatmap-pipeline"},
        )
        # Resolve redirects once (data.police.uk 302s to S3) and learn the size.
        r = self._get_range(url, 0, 0)
        self.url = str(r.url)
        content_range = r.headers.get("content-range", "")
        if "/" not in content_range:
            raise RuntimeError(f"server did not honour Range requests: {content_range!r}")
        self.size = int(content_range.rsplit("/", 1)[1])
        self.members = self._read_central_directory()

    def _get_range(self, url: str, start: int, end: int) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self.client.get(url, headers={"Range": f"bytes={start}-{end}"})
                if r.status_code == 206:
                    return r
                raise RuntimeError(f"expected 206, got {r.status_code}")
            except Exception as exc:  # noqa: BLE001 - retry any transport error
                last_exc = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"range request failed after {self.max_retries} tries: {last_exc}")

    def _read_central_directory(self) -> dict[str, Member]:
        tail_start = max(0, self.size - EOCD_TAIL_FETCH)
        tail = self._get_range(self.url, tail_start, self.size - 1).content

        eocd_pos = tail.rfind(struct.pack("<I", EOCD_SIG))
        if eocd_pos < 0:
            raise RuntimeError("EOCD not found - not a zip?")
        total_entries, cd_size, cd_offset = struct.unpack_from("<HII", tail, eocd_pos + 10)

        if 0xFFFFFFFF in (cd_size, cd_offset) or total_entries == 0xFFFF:
            # zip64: locator sits 20 bytes before EOCD
            loc_pos = eocd_pos - 20
            if struct.unpack_from("<I", tail, loc_pos)[0] != ZIP64_LOCATOR_SIG:
                raise RuntimeError("zip64 sizes but no zip64 locator")
            z64_eocd_offset = struct.unpack_from("<Q", tail, loc_pos + 8)[0]
            z64 = self._get_range(self.url, z64_eocd_offset, z64_eocd_offset + 55).content
            if struct.unpack_from("<I", z64, 0)[0] != ZIP64_EOCD_SIG:
                raise RuntimeError("bad zip64 EOCD signature")
            total_entries = struct.unpack_from("<Q", z64, 32)[0]
            cd_size = struct.unpack_from("<Q", z64, 40)[0]
            cd_offset = struct.unpack_from("<Q", z64, 48)[0]

        cd = self._get_range(self.url, cd_offset, cd_offset + cd_size - 1).content
        members: dict[str, Member] = {}
        pos = 0
        while pos + 46 <= len(cd):
            if struct.unpack_from("<I", cd, pos)[0] != CD_ENTRY_SIG:
                break
            method = struct.unpack_from("<H", cd, pos + 10)[0]
            comp_size = struct.unpack_from("<I", cd, pos + 20)[0]
            uncomp_size = struct.unpack_from("<I", cd, pos + 24)[0]
            fn_len, extra_len, comment_len = struct.unpack_from("<HHH", cd, pos + 28)
            header_offset = struct.unpack_from("<I", cd, pos + 42)[0]
            filename = cd[pos + 46 : pos + 46 + fn_len].decode("utf-8", "replace")

            # zip64 extra field supplies any 0xFFFFFFFF value, in fixed order
            if 0xFFFFFFFF in (comp_size, uncomp_size, header_offset):
                extra = cd[pos + 46 + fn_len : pos + 46 + fn_len + extra_len]
                epos = 0
                while epos + 4 <= len(extra):
                    header_id, data_size = struct.unpack_from("<HH", extra, epos)
                    if header_id == 0x0001:
                        vals = extra[epos + 4 : epos + 4 + data_size]
                        vpos = 0
                        if uncomp_size == 0xFFFFFFFF:
                            uncomp_size = struct.unpack_from("<Q", vals, vpos)[0]
                            vpos += 8
                        if comp_size == 0xFFFFFFFF:
                            comp_size = struct.unpack_from("<Q", vals, vpos)[0]
                            vpos += 8
                        if header_offset == 0xFFFFFFFF:
                            header_offset = struct.unpack_from("<Q", vals, vpos)[0]
                        break
                    epos += 4 + data_size

            members[filename] = Member(filename, method, comp_size, uncomp_size, header_offset)
            pos += 46 + fn_len + extra_len + comment_len

        if total_entries and len(members) != total_entries:
            raise RuntimeError(f"central directory parse mismatch: {len(members)} != {total_entries}")
        return members

    def read_member(self, name: str) -> bytes:
        m = self.members[name]
        header = self._get_range(self.url, m.header_offset, m.header_offset + 29).content
        if struct.unpack_from("<I", header, 0)[0] != LOCAL_HEADER_SIG:
            raise RuntimeError(f"bad local header for {name}")
        fn_len, extra_len = struct.unpack_from("<HH", header, 26)
        data_start = m.header_offset + 30 + fn_len + extra_len
        raw = self._get_range(self.url, data_start, data_start + m.comp_size - 1).content
        if m.method == 0:
            data = raw
        elif m.method == 8:
            data = zlib.decompressobj(-15).decompress(raw)
        else:
            raise RuntimeError(f"unsupported compression method {m.method} for {name}")
        if len(data) != m.uncomp_size:
            raise RuntimeError(f"size mismatch for {name}: {len(data)} != {m.uncomp_size}")
        return data

    def close(self) -> None:
        self.client.close()
