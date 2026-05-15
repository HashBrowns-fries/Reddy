"""QR码 ASCII 渲染 — 零依赖，仅用 Python 标准库

将 PNG 字节转换为终端可显示的 ASCII 字符画。
使用 Unicode 半色调字符 (▀ ▄ █) 实现双倍垂直分辨率。
"""

import struct
import zlib


def png_bytes_to_ascii(png_data: bytes, width: int = 80) -> str:
    """PNG 字节 → 终端 ASCII 字符串

    Args:
        png_data: PNG 文件原始字节
        width: 输出宽度 (字符数)
    """
    if png_data[:8] != b'\x89PNG\r\n\x1a\n':
        return "[Error: not a valid PNG]"

    # 解析 PNG chunks
    img_width = img_height = 0
    img_data = b""

    pos = 8  # skip PNG signature
    while pos < len(png_data):
        chunk_len = struct.unpack(">I", png_data[pos:pos + 4])[0]
        chunk_type = png_data[pos + 4:pos + 8].decode("ascii", errors="replace")
        chunk_data = png_data[pos + 8:pos + 8 + chunk_len]

        if chunk_type == "IHDR":
            img_width = struct.unpack(">I", chunk_data[0:4])[0]
            img_height = struct.unpack(">I", chunk_data[4:8])[0]

        elif chunk_type == "IDAT":
            img_data += chunk_data

        elif chunk_type == "IEND":
            break

        pos += 12 + chunk_len

    if img_width == 0 or img_height == 0:
        return "[Error: cannot parse PNG dimensions]"

    # 解压 IDAT 数据
    raw_data = zlib.decompress(img_data)

    # 从 PNG 原始数据提取 RGBA 像素
    # PNG filter: 每行前 1 字节是 filter type
    bytes_per_pixel = 4  # RGBA
    stride = img_width * bytes_per_pixel + 1  # +1 for filter byte
    pixels = bytearray()
    prev_row = bytearray(img_width * bytes_per_pixel)

    for row_idx in range(img_height):
        row_start = 1 + row_idx * stride
        filter_type = raw_data[row_start - 1]
        row_data = bytearray(raw_data[row_start:row_start + img_width * bytes_per_pixel])

        # Unfilter
        if filter_type == 0:  # None
            pass
        elif filter_type == 1:  # Sub
            for i in range(bytes_per_pixel, len(row_data)):
                row_data[i] = (row_data[i] + row_data[i - bytes_per_pixel]) % 256
        elif filter_type == 2:  # Up
            for i in range(len(row_data)):
                row_data[i] = (row_data[i] + prev_row[i]) % 256
        elif filter_type == 3:  # Average
            for i in range(len(row_data)):
                a = row_data[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                b = prev_row[i]
                row_data[i] = (row_data[i] + (a + b) // 2) % 256
        elif filter_type == 4:  # Paeth
            for i in range(len(row_data)):
                a = row_data[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                b = prev_row[i]
                c = prev_row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                pr = a if pa <= pb and pa <= pc else b if pb <= pc else c
                row_data[i] = (row_data[i] + pr) % 256

        pixels.extend(row_data)
        prev_row = row_data

    # 转换为灰度并渲染为 ASCII
    # 每个输出字符对应 2 行像素 (使用 ▀ ▄ █)
    output_width = min(width, img_width)
    scale_x = img_width / output_width
    scale_y = img_height / (output_width * 2)  # 2 rows per char

    if scale_y < 1:
        scale_y = 1

    char_width = max(1, int(scale_x))
    char_height = max(2, int(scale_y))
    if char_height % 2 != 0:
        char_height += 1  # must be even for block chars

    lines = []
    for y in range(0, img_height - char_height + 1, char_height):
        line = ""
        for x in range(0, img_width - char_width + 1, char_width):
            # 采样上方像素块
            top_bright = _sample_block(pixels, img_width, x, y, char_width, char_height // 2)
            # 采样下方像素块
            bot_bright = _sample_block(pixels, img_width, x, y + char_height // 2, char_width, char_height // 2)

            line += _brightness_pair_to_char(top_bright, bot_bright)
        lines.append(line)

    return "\n".join(lines)


def _sample_block(pixels, img_width, start_x, start_y, w, h) -> float:
    """采样矩形区域的平均亮度 (0-255)"""
    total = 0
    count = 0
    for py in range(start_y, min(start_y + h, len(pixels) // (img_width * 4))):
        for px in range(start_x, min(start_x + w, img_width)):
            idx = (py * img_width + px) * 4
            if idx + 2 < len(pixels):
                r, g, b = pixels[idx], pixels[idx + 1], pixels[idx + 2]
                # 感知亮度权重
                total += 0.299 * r + 0.587 * g + 0.114 * b
                count += 1
    return total / count if count else 0


def render_qrcode_ascii(png_bytes: bytes, width: int = 60) -> str:
    """将 QR 码 PNG 字节渲染为终端 ASCII 字符画"""
    return png_bytes_to_ascii(png_bytes, width=width)


def _brightness_pair_to_char(top: float, bot: float) -> str:
    """将上下两行亮度映射为 Unicode 半色调字符"""
    # 阈值: < 85 暗, 85-170 中, > 170 亮
    def level(v):
        if v < 85:
            return 0  # dark
        if v < 170:
            return 1  # medium
        return 2  # bright

    t, b = level(top), level(bot)
    # ▀ = upper half block, ▄ = lower half block, █ = full block, space = empty
    if t <= 1 and b <= 1:
        return " "  # both dark
    if t >= 1 and b <= 0:
        return "▀"  # ▀ top bright, bottom dark
    if t <= 0 and b >= 1:
        return "▄"  # ▄ top dark, bottom bright
    return "█"  # █ both bright
