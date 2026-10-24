"""
生成应用图标 assets/icon.ico（多尺寸，PNG 压缩内嵌，纯标准库实现）

设计：透明背景 + 一条纯绿色上升曲线（末端带圆点），无底板、无圆角矩形，
      因此在任何桌面/任务栏底色上都能保持干净。
无第三方依赖：手写 PNG 编码器 + ICO 容器封装。
"""
import math
import os
import struct
import zlib

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
PNG_SIZES = {32, 40, 48, 64, 128, 256}   # ≥32 用 PNG；小尺寸用 BMP 保证兼容

GREEN = (0x5E, 0xC5, 0x22)    # #22c55e → BGR
DOT = (0x5E, 0xC5, 0x22)

# 曲线控制点（16 单位为基准，y 向下）
CTRL = [(2.4, 12.6), (5.2, 9.4), (7.4, 11.0), (10.2, 7.0), (13.5, 3.8)]


def _spline(points, seg=24):
    """Catmull-Rom 样条采样，得到平滑折线"""
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(len(pts) - 3):
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        for s in range(seg):
            t = s / seg
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(points[-1])
    return out


def _stamp(alpha, size, cx, cy, radius, hard=1.0):
    """在 alpha 图上叠加一个圆（radius 为半径，边缘 1px 抗锯齿）"""
    x0 = max(0, int(cx - radius - 1.5))
    x1 = min(size - 1, int(cx + radius + 1.5))
    y0 = max(0, int(cy - radius - 1.5))
    y1 = min(size - 1, int(cy + radius + 1.5))
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        for x in range(x0, x1 + 1):
            dx = x + 0.5 - cx
            d = math.hypot(dx, dy)
            cov = radius + 0.5 - d
            if cov <= 0:
                continue
            v = int(255 * min(1.0, cov) * hard)
            if v > alpha[y * size + x]:
                alpha[y * size + x] = v


def _stroke(alpha, size, pts, width):
    """沿折线画一条抗锯齿粗线（逐段限定包围盒，避免全图像素遍历）"""
    r = width / 2.0
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        if seg2 <= 1e-9:
            _stamp(alpha, size, x0, y0, r)
            continue
        bx0 = max(0, int(min(x0, x1) - r - 1.5))
        bx1 = min(size - 1, int(max(x0, x1) + r + 1.5))
        by0 = max(0, int(min(y0, y1) - r - 1.5))
        by1 = min(size - 1, int(max(y0, y1) + r + 1.5))
        for y in range(by0, by1 + 1):
            py = y + 0.5
            for x in range(bx0, bx1 + 1):
                px = x + 0.5
                t = ((px - x0) * dx + (py - y0) * dy) / seg2
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                ddx = px - (x0 + dx * t)
                ddy = py - (y0 + dy * t)
                cov = r + 0.5 - math.hypot(ddx, ddy)
                if cov <= 0:
                    continue
                v = int(255 * min(1.0, cov))
                if v > alpha[y * size + x]:
                    alpha[y * size + x] = v


def render(size):
    """渲染 size×size 的 32bit BGRA 像素（自上而下）；背景完全透明"""
    alpha = bytearray(size * size)
    unit = size / 16.0
    pts = [(x * unit, y * unit) for x, y in _spline(CTRL)]
    width = max(2.0, size * 0.125)
    _stroke(alpha, size, pts, width)
    # 末端圆点，像「最新价」的定位点
    ex, ey = CTRL[-1][0] * unit, CTRL[-1][1] * unit
    _stamp(alpha, size, ex, ey, width * 0.78)

    px = []
    for y in range(size):
        row = []
        for x in range(size):
            a = alpha[y * size + x]
            if a:
                row.append((GREEN[0], GREEN[1], GREEN[2], a))
            else:
                row.append((0, 0, 0, 0))
        px.append(row)
    return px


# ---------------------------------------------------------------- PNG 编码

def _chunk(tag, data):
    c = struct.pack('>I', len(data)) + tag + data
    return c + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def png_bytes(px, size):
    """将 RGBA 像素（自上而下）编码为 PNG"""
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type 0
        row = px[y]
        for x in range(size):
            b, g, r, a = row[x]
            raw += bytes((r, g, b, a))
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + _chunk(b'IEND', b''))


def bmp_dib(px, size):
    """生成 BITMAPINFOHEADER + BGRA 像素（ICO 内嵌格式，height 为 2 倍）"""
    header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    data = bytearray()
    for y in range(size - 1, -1, -1):   # 自下而上
        for x in range(size):
            b, g, r, a = px[y][x]
            data += bytes((b, g, r, a))
    and_mask = bytes(((size + 31) // 32) * 4 * size)   # 全 0：使用 alpha 通道
    return header + bytes(data) + and_mask


def build_ico(path):
    images = []
    for s in SIZES:
        px = render(s)
        if s in PNG_SIZES:
            images.append((s, png_bytes(px, s)))
        else:
            images.append((s, bmp_dib(px, s)))

    out = bytearray(struct.pack('<HHH', 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    dir_entries = bytearray()
    for s, data in images:
        dim = 0 if s >= 256 else s
        dir_entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += dir_entries
    for _s, data in images:
        out += data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(bytes(out))
    return len(out), [(s, len(d)) for s, d in images]


def raw_ico_bytes(path=None):
    here = os.path.dirname(os.path.abspath(__file__))
    p = path or os.path.join(here, 'assets', 'icon.ico')
    with open(p, 'rb') as f:
        return f.read()


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, 'assets', 'icon.ico')
    n, detail = build_ico(p)
    print(f'[icon] {p}')
    print(f'[icon] 总大小 {n} bytes ({n/1024:.1f} KB)')
    for s, ln in detail:
        print(f'       {s:>3}px  {ln:>7} bytes  {"PNG" if s in PNG_SIZES else "BMP"}')
