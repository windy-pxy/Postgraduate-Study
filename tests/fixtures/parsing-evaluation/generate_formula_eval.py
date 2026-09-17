"""Generate two synthetic one-page PDFs for formula/symbol extraction evaluation."""
from argparse import ArgumentParser
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


def label(pdf, x, y, text, size=12):
    pdf.setFont('STSong-Light', size)
    pdf.drawString(x, y, text)


def latin(pdf, x, y, text, size=13):
    pdf.setFont('Times-Roman', size)
    pdf.drawString(x, y, text)


def subscript(pdf, x, y, base, sub, suffix='', size=15):
    latin(pdf, x, y, base, size)
    width = pdfmetrics.stringWidth(base, 'Times-Roman', size)
    latin(pdf, x + width + 1, y - 4, sub, size * 0.65)
    sub_width = pdfmetrics.stringWidth(sub, 'Times-Roman', size * 0.65)
    if suffix:
        latin(pdf, x + width + sub_width + 3, y, suffix, size)


def fraction(pdf, x, y, numerator, denominator):
    latin(pdf, x + 10, y + 8, numerator, 13)
    latin(pdf, x + 12, y - 10, denominator, 13)
    pdf.setLineWidth(1)
    pdf.line(x, y + 4, x + 55, y + 4)


def common_header(pdf, split):
    label(pdf, 48, 800, '数学一与408公式增强解析合成评估', 16)
    latin(pdf, 48, 778, f'SPLIT: {split} / synthetic content only', 10)
    pdf.setLineWidth(0.5)
    pdf.line(48, 770, 545, 770)


def draw_development(path):
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=0)
    common_header(pdf, 'development')
    label(pdf, 48, 742, '1. 下标与上下标混排：')
    subscript(pdf, 205, 742, 'x', '1')
    subscript(pdf, 245, 742, 'x', '2')
    subscript(pdf, 285, 742, 'x', 'n+1')
    latin(pdf, 345, 742, 'a', 15)
    latin(pdf, 354, 749, '2', 9)
    subscript(pdf, 370, 742, 'b', 'i')

    label(pdf, 48, 704, '2. 补码与二进制位号： [X]补 = 10110110，符号位 b')
    latin(pdf, 437, 700, '7', 9)
    label(pdf, 448, 704, '，最低位 b')
    latin(pdf, 504, 700, '0', 9)
    label(pdf, 515, 704, '。')
    label(pdf, 70, 680, '关系检查： -7 < -3，且 0 ≤ i < 8。')

    label(pdf, 48, 642, '3. 分式、根号、求和、极限与积分：')
    fraction(pdf, 285, 642, 'x + 1', 'x - 1')
    label(pdf, 352, 642, '，√(a²+b²)，')
    latin(pdf, 438, 642, 'Σ', 18)
    subscript(pdf, 456, 642, '', 'i=1', ' x', 13)
    latin(pdf, 495, 650, 'n', 9)
    label(pdf, 70, 610, 'lim')
    subscript(pdf, 90, 610, '', 'x→0', ' sin(x)/x = 1', 13)
    latin(pdf, 260, 610, '∫', 20)
    latin(pdf, 275, 618, '1', 8)
    latin(pdf, 275, 602, '0', 8)
    latin(pdf, 287, 610, 'x', 13)
    latin(pdf, 296, 617, '2', 8)
    latin(pdf, 306, 610, ' dx = 1/3', 13)

    label(pdf, 48, 566, '4. 矩阵与分段函数：')
    latin(pdf, 205, 566, 'A = ( 1  2 )', 14)
    latin(pdf, 244, 546, '    ( 3  4 )', 14)
    latin(pdf, 350, 566, 'f(x) = { x,   x >= 0', 13)
    latin(pdf, 395, 546, '       -x,  x < 0', 13)

    label(pdf, 48, 500, '5. 中文与公式混排：当矩阵 A 可逆时，')
    latin(pdf, 300, 500, 'AA', 14)
    latin(pdf, 318, 507, '-1', 8)
    latin(pdf, 330, 500, '= I', 14)
    label(pdf, 355, 500, '，结论中的次序不可交换。')

    label(pdf, 48, 458, '6. 代码标识符与数组下标： array[i+1] = cache_line[tag_bits]')
    label(pdf, 48, 420, '7. 简单表格与选项顺序：')
    rows = [('位号', '7', '0'), ('字段', 'tag', 'offset'), ('选择', 'A', 'B')]
    x0, y0, widths, height = 70, 390, (90, 130, 130), 24
    for row_index, row in enumerate(rows):
        y = y0 - row_index * height
        x = x0
        for col, width in zip(row, widths):
            pdf.rect(x, y, width, height)
            label(pdf, x + 6, y + 7, col, 10)
            x += width
    label(pdf, 70, 292, 'A. 保留题干顺序    B. 不交换选项    C. 不遗漏数字    D. 人工复核')
    pdf.save()


def draw_holdout(path):
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=0)
    common_header(pdf, 'held_out')
    label(pdf, 48, 736, '留出样本：以下内容不得用于阈值调参。')
    label(pdf, 48, 700, '1. 序列关系：')
    subscript(pdf, 145, 700, 'u', 'k+1', size=14)
    latin(pdf, 185, 700, ' = 2', 14)
    subscript(pdf, 220, 700, 'u', 'k', size=14)
    latin(pdf, 242, 700, ' - ', 14)
    subscript(pdf, 260, 700, 'u', 'k-1', '.', 14)
    label(pdf, 48, 658, '2. 机器数： [Y]原 ≠ [Y]补，-128 ≤ Y ≤ 127。')
    label(pdf, 48, 616, '3. 地址字段： address[31:12] | index[11:5] | offset[4:0]。')
    label(pdf, 48, 574, '4. 中文与积分：设函数连续，则')
    latin(pdf, 250, 574, '∫', 20)
    latin(pdf, 265, 582, 'b', 8)
    latin(pdf, 265, 566, 'a', 8)
    latin(pdf, 277, 574, ' f(x) dx', 14)
    label(pdf, 345, 574, '保持上下限次序。')
    label(pdf, 48, 532, '5. 矩阵行列式： det(B) = ad - bc，不得写成 ad + bc。')
    label(pdf, 48, 490, '6. 选项顺序： A. 00  B. 01  C. 10  D. 11')
    pdf.save()


def main():
    parser = ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    if output.exists():
        raise SystemExit('OUTPUT_EXISTS')
    output.mkdir(parents=True)
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    draw_development(output / 'formula-development.pdf')
    draw_holdout(output / 'formula-held-out.pdf')
    print('generated=2')


if __name__ == '__main__':
    main()
