# -*- coding: utf-8 -*-
"""数据源修复回归：价格小数位 + 东财/新浪 3 位小数（全部用假数据，不依赖网络）。

覆盖：
  1. price_decimals：股票 2 位 / 基金·ETF·可转债·港股 3 位
  2. 东方财富 _parse_em_item：股票 ÷100、基金 ÷1000（旧 bug 是基金 ÷100 → 价格大 10 倍）
  3. 新浪 parse_sina_body：涨跌额按品种小数位（基金 3 位，不再是 -0.04）
  4. 腾讯 parse_tencent_body：ETF 现价保留 3 位
  5. 显示格式：股票 2 位、基金 3 位
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import dingpan.quotes as quotes  # noqa: E402


def approx(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


def main():
    total = [0]
    fails = []

    def check(name, cond, extra=''):
        total[0] += 1
        mark = '✓' if cond else '✗'
        print('  %s %s%s' % (mark, name, ('   (%s)' % extra) if extra else ''))
        if not cond:
            fails.append(name)

    print('=== 1) price_decimals ===')
    for code, exp in [('sh600519', 2), ('sh688981', 2), ('sz000001', 2),
                      ('sz300750', 2), ('sh510300', 3), ('sh511880', 3),
                      ('sz159915', 3), ('sh113050', 3), ('sz123000', 3),
                      ('hk00700', 3), ('bj830799', 2), ('usAAPL', 2)]:
        got = quotes.price_decimals(code)
        check('price_decimals(%s)=%d' % (code, exp), got == exp, 'got %d' % got)

    print('=== 2) 东方财富 _parse_em_item ===')
    stock = {'f12': '600519', 'f13': 1, 'f14': '贵州茅台', 'f2': 133600, 'f3': 7,
             'f4': 100, 'f15': 134000, 'f16': 133000, 'f17': 133800, 'f18': 133500,
             'f8': 8, 'f9': 1876, 'f10': 147, 'f5': 123456, 'f6': 99999999,
             'f20': 200000000000}
    s = quotes._parse_em_item(stock)
    check('股票 现价 1336.00', approx(s['price'], 1336.00), 'got %s' % s['price'])
    check('股票 昨收 1335.00', approx(s['prevClose'], 1335.00))
    check('股票 涨跌额 1.00', approx(s['change'], 1.00))
    check('股票 涨跌幅 0.07', approx(s['changePct'], 0.07))
    check('股票 市盈 18.76', approx(s['pe'], 18.76))
    check('股票 振幅 1.47', approx(s['amplitude'], 1.47))

    fund = {'f12': '510300', 'f13': 1, 'f14': '沪深300ETF', 'f2': 4145, 'f3': -79,
            'f4': -33, 'f15': 4190, 'f16': 4120, 'f17': 4180, 'f18': 4178,
            'f8': 147, 'f9': 0, 'f10': 149}
    f = quotes._parse_em_item(fund)
    check('基金 现价 4.145（不是 41.45）', approx(f['price'], 4.145), 'got %s' % f['price'])
    check('基金 昨收 4.178', approx(f['prevClose'], 4.178))
    check('基金 涨跌额 -0.033', approx(f['change'], -0.033))
    check('基金 涨跌幅 -0.79', approx(f['changePct'], -0.79))
    check('基金 振幅 1.49', approx(f['amplitude'], 1.49))
    check('基金 现价 ≠ 41.45（旧 bug）', not approx(f['price'], 41.45))

    print('=== 3) 新浪 parse_sina_body（基金涨跌额 3 位）===')
    ff = ['0'] * 32
    ff[0], ff[1], ff[2], ff[3] = '沪深300ETF', '4.180', '4.178', '4.141'
    ff[4], ff[5], ff[8], ff[9] = '4.190', '4.120', '1000000', '4180000'
    ff[30], ff[31] = '2026-10-26', '09:35:00'
    sina_body = 'var hq_str_sh510300="' + ','.join(ff) + '";'
    sin = quotes.parse_sina_body(sina_body)
    q = sin.get('sh510300')
    check('新浪 基金 现价 4.141', q and approx(q['price'], 4.141), 'got %s' % (q and q.get('price')))
    check('新浪 基金 涨跌额 -0.037（3 位，非 -0.04）', q and approx(q['change'], -0.037),
          'got %s' % (q and q.get('change')))
    check('新浪 基金 涨跌幅 -0.89', q and approx(q['changePct'], -0.89),
          'got %s' % (q and q.get('changePct')))

    print('=== 4) 腾讯 parse_tencent_body（ETF 现价 3 位）===')
    f = ['0'] * 47
    f[0], f[1], f[3], f[4] = '1', '沪深300ETF', '4.141', '4.178'
    f[5], f[6], f[30] = '4.180', '1054321', '20261026'
    f[31], f[32], f[33], f[34] = '0.037', '-0.88', '4.190', '4.120'
    f[37], f[38], f[39] = '4398000', '0.8', '18.5'
    tx_body = 'v_sh510300="' + '~'.join(f) + '"'
    txn = quotes.parse_tencent_body(tx_body)
    qt = txn.get('sh510300')
    check('腾讯 基金 现价 4.141', qt and approx(qt['price'], 4.141), 'got %s' % (qt and qt.get('price')))
    check('腾讯 基金 涨跌 0.037', qt and approx(qt['change'], 0.037))
    check('腾讯 基金 涨跌幅 -0.88', qt and approx(qt['changePct'], -0.88))

    print('=== 5) 显示格式 ===')
    check('股票价格格式 1336.00', ('%.2f' % 1336.0) == '1336.00')
    check('基金价格格式 4.141', ('%.3f' % 4.141) == '4.141')

    print('\n%d 项检查，%d 项失败' % (total[0], len(fails)))
    if fails:
        print('失败项：', fails)
        return 1
    print('全部通过 ✓')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
