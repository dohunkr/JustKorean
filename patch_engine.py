"""Godot 4 encrypted PCK / GDC / RSRC / FontFile patching engine for Just Volleyball."""

from __future__ import annotations

import hashlib
import os
import struct
from typing import Callable, Dict, Optional

import zstandard
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Extracted from volleyball.exe (Godot 4.7.1 script_encryption_key)
PCK_KEY = bytes.fromhex(
    "a70ce17f5acc28c5b241f1b901ddc07fbb9d2679d9cda21c31865127914e25c6"
)


def aes_cfb_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CFB(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def aes_cfb_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.CFB(iv)).encryptor()
    return enc.update(data) + enc.finalize()


def decrypt_fae(raw: bytes, key: bytes = PCK_KEY) -> bytes:
    md5_exp = raw[0:16]
    orig_size = struct.unpack_from("<Q", raw, 16)[0]
    iv = raw[24:40]
    pad_sz = ((orig_size + 15) // 16) * 16
    dec = aes_cfb_decrypt(key, iv, raw[40 : 40 + pad_sz])[:orig_size]
    if hashlib.md5(dec).digest() != md5_exp:
        raise ValueError("FAE MD5 mismatch during decryption")
    return dec


def encrypt_fae(plain: bytes, key: bytes = PCK_KEY) -> bytes:
    md5 = hashlib.md5(plain).digest()
    orig_size = len(plain)
    iv = os.urandom(16)
    pad_len = (-orig_size) % 16
    padded = plain + (b"\x00" * pad_len)
    enc = aes_cfb_encrypt(key, iv, padded)
    return md5 + struct.pack("<Q", orig_size) + iv + enc


def to_rsrc(data: bytes) -> bytes:
    """Convert RSCC (Zstd compressed Godot binary resource) to uncompressed RSRC."""
    if data[:4] == b"RSRC":
        return data
    if data[:4] != b"RSCC":
        raise ValueError(f"Unexpected resource magic: {data[:4]!r}")
    _mode, block_size, total_size = struct.unpack_from("<III", data, 4)
    num_blocks = (total_size + block_size - 1) // block_size
    block_sizes = struct.unpack_from(f"<{num_blocks}I", data, 16)
    pos = 16 + num_blocks * 4
    dctx = zstandard.ZstdDecompressor()
    out = bytearray(b"RSRC")
    for bsz in block_sizes:
        chunk = data[pos : pos + bsz]
        pos += bsz
        cur = len(out) - 4
        expected = block_size if cur + block_size <= total_size else (total_size - cur)
        if bsz == expected:
            out.extend(chunk)
        else:
            out.extend(dctx.decompress(chunk, max_output_size=expected))
    return bytes(out)


def _read_ustring(buf: bytes, pos: int) -> tuple[str, int]:
    ln = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    s = buf[pos : pos + ln].rstrip(b"\x00").decode("utf-8", errors="replace")
    return s, pos + ln


def _pack_ustring(s: str) -> bytes:
    raw = s.encode("utf-8") + b"\x00"
    return struct.pack("<I", len(raw)) + raw


def _skip_variant(buf: bytes, pos: int) -> int:
    vtype = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    if vtype == 1:
        pass
    elif vtype in (2, 3, 4):
        pos += 4
    elif vtype in (5, 26):
        _, pos = _read_ustring(buf, pos)
    elif vtype in (10, 27):
        pos += 8
    elif vtype in (11, 13, 14, 20, 28):
        pos += 16
    elif vtype == 12:
        pos += 12
    elif vtype in (15, 18):
        pos += 24
    elif vtype == 16:
        pos += 36
    elif vtype == 17:
        pos += 48
    elif vtype == 21:
        nc, sc, _fl = struct.unpack_from("<III", buf, pos)
        pos += 12
        for _ in range(nc + sc):
            _, pos = _read_ustring(buf, pos)
    elif vtype == 24:
        ot = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        if ot in (2, 3):
            pos += 4
        elif ot == 1:
            _, pos = _read_ustring(buf, pos)
            _, pos = _read_ustring(buf, pos)
    elif vtype == 25:
        pass
    elif vtype == 29:
        cnt = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        for _ in range(cnt & 0x7FFFFFFF):
            pos = _skip_variant(buf, pos)
            pos = _skip_variant(buf, pos)
    elif vtype == 30:
        cnt = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        for _ in range(cnt & 0x7FFFFFFF):
            pos = _skip_variant(buf, pos)
    elif vtype == 31:
        ln = struct.unpack_from("<I", buf, pos)[0]
        pos += 4 + ((ln + 3) & ~3)
    elif vtype in (32, 33):
        ln = struct.unpack_from("<I", buf, pos)[0]
        pos += 4 + ln * 4
    elif vtype == 34:
        ln = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        for _ in range(ln):
            _, pos = _read_ustring(buf, pos)
    elif vtype in (40, 41):
        pos += 8
    else:
        raise ValueError(f"Unsupported RSRC variant type: {vtype} at {pos - 4}")
    return pos


def _shift_rsrc_offsets(buf: bytearray, from_pos: int, delta: int) -> None:
    """Adjust internal resource offset table entries >= from_pos by delta."""
    if delta == 0:
        return
    pos = 24
    _, pos = _read_ustring(buf, pos)
    _imp_ofs, flags, _uid = struct.unpack_from("<QIQ", buf, pos)
    pos += 20
    if flags & 8:
        _, pos = _read_ustring(buf, pos)
    pos += 44
    sc = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    for _ in range(sc):
        _, pos = _read_ustring(buf, pos)
    ec = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    for _ in range(ec):
        _, pos = _read_ustring(buf, pos)
        _, pos = _read_ustring(buf, pos)
        if flags & 2:
            pos += 8
    ic = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    for _ in range(ic):
        _, pos = _read_ustring(buf, pos)
        ioff = struct.unpack_from("<Q", buf, pos)[0]
        if ioff >= from_pos:
            struct.pack_into("<Q", buf, pos, ioff + delta)
        pos += 8


def patch_fontdata(raw: bytes, ttf_bytes: bytes) -> bytes:
    """Replace FontFile's embedded TTF/OTF `data` PackedByteArray and return uncompressed RSRC."""
    was_rscc = raw[:4] == b"RSCC"
    rsrc = bytearray(to_rsrc(raw))

    # In RSCC, internal offsets were stored relative to post-"RSRC" (4 bytes earlier).
    if was_rscc:
        _shift_rsrc_offsets(rsrc, 0, 4)

    # Locate internal FontFile resource
    pos = 24
    _, pos = _read_ustring(rsrc, pos)
    _imp_ofs, flags, _uid = struct.unpack_from("<QIQ", rsrc, pos)
    pos += 20
    if flags & 8:
        _, pos = _read_ustring(rsrc, pos)
    pos += 44
    sc = struct.unpack_from("<I", rsrc, pos)[0]
    pos += 4
    strings = []
    for _ in range(sc):
        s, pos = _read_ustring(rsrc, pos)
        strings.append(s)
    ec = struct.unpack_from("<I", rsrc, pos)[0]
    pos += 4
    for _ in range(ec):
        _, pos = _read_ustring(rsrc, pos)
        _, pos = _read_ustring(rsrc, pos)
        if flags & 2:
            pos += 8
    ic = struct.unpack_from("<I", rsrc, pos)[0]
    assert ic == 1
    pos += 4
    _, pos = _read_ustring(rsrc, pos)
    ioff = struct.unpack_from("<Q", rsrc, pos)[0]

    p = ioff
    _, p = _read_ustring(rsrc, p)
    pc = struct.unpack_from("<I", rsrc, p)[0]
    p += 4
    for _ in range(pc):
        nidx, vtype = struct.unpack_from("<II", rsrc, p)
        p += 8
        if strings[nidx] == "data" and vtype == 31:
            old_len = struct.unpack_from("<I", rsrc, p)[0]
            old_total = 4 + ((old_len + 3) & ~3)
            new_len = len(ttf_bytes)
            pad = (-new_len) % 4
            new_blob = struct.pack("<I", new_len) + ttf_bytes + (b"\x00" * pad)
            rsrc[p : p + old_total] = new_blob
            return bytes(rsrc)
        p = _skip_variant(rsrc, p - 4)
    raise ValueError("FontFile `data` property not found")


def patch_res_text(raw: bytes, prop_name: str, new_text: str) -> bytes:
    """Replace a string property in a single-resource RSRC/RSCC file."""
    was_rscc = raw[:4] == b"RSCC"
    rsrc = bytearray(to_rsrc(raw))
    if was_rscc:
        _shift_rsrc_offsets(rsrc, 0, 4)

    pos = 24
    _, pos = _read_ustring(rsrc, pos)
    _imp_ofs, flags, _uid = struct.unpack_from("<QIQ", rsrc, pos)
    pos += 20
    if flags & 8:
        _, pos = _read_ustring(rsrc, pos)
    pos += 44
    sc = struct.unpack_from("<I", rsrc, pos)[0]
    pos += 4
    strings = []
    for _ in range(sc):
        s, pos = _read_ustring(rsrc, pos)
        strings.append(s)
    ec = struct.unpack_from("<I", rsrc, pos)[0]
    pos += 4
    for _ in range(ec):
        _, pos = _read_ustring(rsrc, pos)
        _, pos = _read_ustring(rsrc, pos)
        if flags & 2:
            pos += 8
    ic = struct.unpack_from("<I", rsrc, pos)[0]
    pos += 4
    _, pos = _read_ustring(rsrc, pos)
    ioff = struct.unpack_from("<Q", rsrc, pos)[0]

    p = ioff
    _, p = _read_ustring(rsrc, p)
    pc = struct.unpack_from("<I", rsrc, p)[0]
    p += 4
    for _ in range(pc):
        nidx, vtype = struct.unpack_from("<II", rsrc, p)
        p += 8
        if strings[nidx] == prop_name and vtype == 5:
            old_ln = struct.unpack_from("<I", rsrc, p)[0]
            old_end = p + 4 + old_ln
            new_blob = _pack_ustring(new_text)
            delta = len(new_blob) - (old_end - p)
            rsrc[p:old_end] = new_blob
            _shift_rsrc_offsets(rsrc, old_end, delta)
            return bytes(rsrc)
        p = _skip_variant(rsrc, p - 4)
    raise ValueError(f"Property {prop_name!r} not found in .res")


def patch_scn_variants(raw: bytes, replacements: Dict[str, str]) -> bytes:
    """Replace string variants in PackedScene _bundled.variants.

    Supports both index-keyed (str(idx) -> new_text) and orig-text-keyed (orig -> new_text).
    """
    was_rscc = raw[:4] == b"RSCC"
    rsrc = bytearray(to_rsrc(raw))
    if was_rscc:
        _shift_rsrc_offsets(rsrc, 0, 4)

    vkey = b"\x05\x00\x00\x00\x09\x00\x00\x00variants\x00"
    vpos = rsrc.find(vkey)
    if vpos == -1:
        raise ValueError("PackedScene _bundled.variants not found")
    pos = vpos + len(vkey)
    vtype = struct.unpack_from("<I", rsrc, pos)[0]
    if vtype != 30:
        raise ValueError(f"Expected Array (30), got {vtype}")
    pos += 4
    cnt = struct.unpack_from("<I", rsrc, pos)[0] & 0x7FFFFFFF
    pos += 4

    for i in range(cnt):
        elem_vtype = struct.unpack_from("<I", rsrc, pos)[0]
        key = str(i)
        if elem_vtype == 5:
            spos = pos + 4
            old_ln = struct.unpack_from("<I", rsrc, spos)[0]
            old_str = rsrc[spos + 4 : spos + 4 + old_ln].rstrip(b"\x00").decode("utf-8", errors="replace")
            new_text = replacements.get(key) or replacements.get(old_str)
            if new_text:
                old_end = spos + 4 + old_ln
                new_blob = _pack_ustring(new_text)
                delta = len(new_blob) - (old_end - spos)
                rsrc[spos:old_end] = new_blob
                _shift_rsrc_offsets(rsrc, old_end, delta)
                pos = spos + len(new_blob)
                continue
        pos = _skip_variant(rsrc, pos)
    return bytes(rsrc)


def patch_gdc(raw: bytes, replacements: Dict[str, object]) -> bytes:
    """Replace string constants in GDSC bytecode by matching original string text.

    replacements can map either str(const_idx) -> {"orig": str, "ko": str}
    or orig_str -> ko_str directly (version-resilient).
    """
    if raw[:4] != b"GDSC":
        raise ValueError("Not a GDSC file")
    orig_to_ko: Dict[str, str] = {}
    for v in replacements.values() if False else []:
        pass
    for k, v in replacements.items():
        if isinstance(v, dict):
            orig_to_ko[v["orig"]] = v["ko"]
        elif isinstance(v, str):
            orig_to_ko[k] = v

    ver, dec_sz = struct.unpack_from("<II", raw, 4)
    dec = (
        raw[12:]
        if dec_sz == 0
        else zstandard.ZstdDecompressor().decompress(raw[12:], max_output_size=dec_sz)
    )
    out = bytearray()
    pos = 0
    id_count, const_count, line_count, token_count = struct.unpack_from("<IIII", dec, pos)
    pos += 16
    for _ in range(id_count):
        slen = struct.unpack_from("<I", dec, pos)[0]
        pos += 4 + slen * 4
    out.extend(dec[:pos])

    for i in range(const_count):
        vtype = struct.unpack_from("<I", dec, pos)[0]
        bt = vtype & 0xFFFF
        fl = vtype >> 16
        if bt in (4, 21):
            slen = struct.unpack_from("<I", dec, pos + 4)[0]
            s_bytes = dec[pos + 8 : pos + 8 + slen]
            padded_end = pos + 8 + ((slen + 3) & ~3)
            if bt == 4:
                orig_s = s_bytes.decode("utf-8", errors="replace")
                if orig_s in orig_to_ko:
                    ko_bytes = orig_to_ko[orig_s].encode("utf-8")
                    pad = (-len(ko_bytes)) % 4
                    out.extend(struct.pack("<II", vtype, len(ko_bytes)))
                    out.extend(ko_bytes + (b"\x00" * pad))
                    pos = padded_end
                    continue
            out.extend(dec[pos:padded_end])
            pos = padded_end
        else:
            start = pos
            pos += 4
            if bt == 0:
                pass
            elif bt == 1:
                pos += 4
            elif bt in (2, 3):
                pos += 8 if (fl & 1) else 4
            elif bt == 5:
                pos += 16 if (fl & 1) else 8
            elif bt == 6:
                pos += 8
            elif bt == 7:
                pos += 32 if (fl & 1) else 16
            elif bt == 8:
                pos += 16
            elif bt == 9:
                pos += 24 if (fl & 1) else 12
            elif bt == 10:
                pos += 12
            elif bt == 12:
                pos += 32 if (fl & 1) else 16
            elif bt == 20:
                pos += 16
            elif bt == 22:
                nc, sc, _np_flags = struct.unpack_from("<III", dec, pos)
                pos += 12
                for _ in range((nc & 0x7FFFFFFF) + sc):
                    slen = struct.unpack_from("<I", dec, pos)[0]
                    pos += 4 + ((slen + 3) & ~3)
            else:
                raise ValueError(f"Unsupported GDC constant type {bt} at idx {i}")
            out.extend(dec[start:pos])

    out.extend(dec[pos:])
    new_dec = bytes(out)
    comp = zstandard.ZstdCompressor(level=6).compress(new_dec)
    return b"GDSC" + struct.pack("<II", ver, len(new_dec)) + comp


def is_pck_patched(pck_path: str) -> bool:
    """Return True if volleyball.pck already contains Korean-patched how_to_text.json."""
    try:
        with open(pck_path, "rb") as f:
            header = f.read(112)
            if header[:4] != b"GDPC":
                return False
            file_base = struct.unpack_from("<Q", header, 24)[0]
            dir_off = struct.unpack_from("<Q", header, 32)[0]
            f.seek(dir_off)
            file_count = struct.unpack("<I", f.read(4))[0]
            f.read(16)
            enc_size = struct.unpack("<Q", f.read(8))[0]
            iv = f.read(16)
            dec_dir = aes_cfb_decrypt(PCK_KEY, iv, f.read())[:enc_size]
            pos = 0
            for _ in range(file_count):
                plen = struct.unpack_from("<I", dec_dir, pos)[0]
                pos += 4
                path = dec_dir[pos : pos + plen].rstrip(b"\x00").decode("utf-8", errors="replace")
                pos += plen
                off, sz = struct.unpack_from("<QQ", dec_dir, pos)
                pos += 36
                if path == "game/ui/how_to_text.json":
                    f.seek(file_base + off)
                    plain = decrypt_fae(f.read(40 + ((sz + 15) // 16) * 16), PCK_KEY)
                    txt = plain.decode("utf-8", errors="ignore")
                    return "조작" in txt or "배구" in txt
        return False
    except Exception:
        return False


def rebuild_pck(
    src_pck: str,
    dst_pck: str,
    patch_fn_map: Dict[str, Callable[[bytes], bytes]],
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    """Stream-rebuild encrypted Godot 4 PCK, patching only files in patch_fn_map."""
    with open(src_pck, "rb") as f:
        header = f.read(112)
        magic = header[:4]
        if magic != b"GDPC":
            raise ValueError("Invalid PCK magic")
        fmt_ver, vmaj, vmin, vpatch, flags = struct.unpack_from("<IIIII", header, 4)
        file_base = struct.unpack_from("<Q", header, 24)[0]
        dir_off = struct.unpack_from("<Q", header, 32)[0]

        f.seek(dir_off)
        file_count = struct.unpack("<I", f.read(4))[0]
        _md5_dir = f.read(16)
        enc_size = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
        dec_dir = aes_cfb_decrypt(PCK_KEY, iv, f.read())[:enc_size]

        entries = []
        pos = 0
        for _ in range(file_count):
            plen = struct.unpack_from("<I", dec_dir, pos)[0]
            pos += 4
            path_bytes = dec_dir[pos : pos + plen]
            path = path_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")
            pos += plen
            off, sz = struct.unpack_from("<QQ", dec_dir, pos)
            pos += 16
            fmd5 = dec_dir[pos : pos + 16]
            pos += 16
            fflags = struct.unpack_from("<I", dec_dir, pos)[0]
            pos += 4
            entries.append((path, path_bytes, off, sz, fmd5, fflags))

        new_entries = []
        with open(dst_pck, "wb") as out:
            out.write(header)
            cur_rel_off = 0
            for idx, (path, path_bytes, off, sz, fmd5, fflags) in enumerate(entries):
                if progress_cb and idx % 200 == 0:
                    progress_cb(idx, file_count, path)

                if path in patch_fn_map:
                    f.seek(file_base + off)
                    if fflags & 1:
                        hdr = f.read(40)
                        sz2 = struct.unpack_from("<Q", hdr, 16)[0]
                        iv2 = hdr[24:40]
                        pad_sz = ((sz2 + 15) // 16) * 16
                        plain = aes_cfb_decrypt(PCK_KEY, iv2, f.read(pad_sz))[:sz2]
                    else:
                        plain = f.read(sz)

                    new_plain = patch_fn_map[path](plain)
                    new_md5 = hashlib.md5(new_plain).digest()
                    new_sz = len(new_plain)
                    if fflags & 1:
                        blob = encrypt_fae(new_plain, PCK_KEY)
                    else:
                        blob = new_plain
                    out.write(blob)
                    new_entries.append((path_bytes, cur_rel_off, new_sz, new_md5, fflags))
                    cur_rel_off += len(blob)
                else:
                    # Copy raw encrypted/plain chunk directly from source PCK
                    f.seek(file_base + off)
                    if fflags & 1:
                        raw_len = 40 + ((sz + 15) // 16) * 16
                    else:
                        raw_len = sz
                    remaining = raw_len
                    while remaining > 0:
                        chunk = f.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise EOFError(f"Unexpected EOF reading {path}")
                        out.write(chunk)
                        remaining -= len(chunk)
                    new_entries.append((path_bytes, cur_rel_off, sz, fmd5, fflags))
                    cur_rel_off += raw_len

            new_dir_off = out.tell()
            dir_buf = bytearray()
            for path_bytes, rel_off, sz, fmd5, fflags in new_entries:
                dir_buf.extend(struct.pack("<I", len(path_bytes)))
                dir_buf.extend(path_bytes)
                dir_buf.extend(struct.pack("<QQ", rel_off, sz))
                dir_buf.extend(fmd5)
                dir_buf.extend(struct.pack("<I", fflags))

            dir_plain = bytes(dir_buf)
            dir_md5 = hashlib.md5(dir_plain).digest()
            dir_iv = os.urandom(16)
            pad_len = (-len(dir_plain)) % 16
            dir_enc = aes_cfb_encrypt(PCK_KEY, dir_iv, dir_plain + (b"\x00" * pad_len))

            out.write(struct.pack("<I", len(new_entries)))
            out.write(dir_md5)
            out.write(struct.pack("<Q", len(dir_plain)))
            out.write(dir_iv)
            out.write(dir_enc)

            # Update dir_offset in header (offset 32)
            out.seek(32)
            out.write(struct.pack("<Q", new_dir_off))

        if progress_cb:
            progress_cb(file_count, file_count, "완료")
