interface ValidationResult {
  valid: boolean;
  message?: string;
  normalized: string;
}

// Market selector for the analyze input. The user must pick a market; the
// chosen market always drives how the code is interpreted (no auto-detect).
export type Market = 'cn' | 'hk' | 'us';

/**
 * Apply the selected market to a raw stock code.
 *
 * Only HK needs help: a bare 5-digit code (e.g. "00700") is ambiguous with an
 * A-share code downstream, so when the user picks 港股 we append ".HK" to make
 * it unambiguous. A-share / US codes need no suffix. Already-qualified HK codes
 * (HK-prefixed or .HK-suffixed) are left untouched.
 */
export const applyMarketSuffix = (value: string, market: Market): string => {
  const c = value.trim().toUpperCase();
  if (!c) return c;
  if (market === 'hk' && !c.endsWith('.HK') && !c.startsWith('HK')) {
    return `${c}.HK`;
  }
  return c;
};

// 兼容 A/H/美股常见代码格式的基础校验
export const validateStockCode = (value: string): ValidationResult => {
  const normalized = value.trim().toUpperCase();

  if (!normalized) {
    return { valid: false, message: '请输入股票代码', normalized };
  }

  const patterns = [
    /^\d{6}$/, // A 股 6 位数字
    /^(SH|SZ)\d{6}$/, // A 股带交易所前缀
    /^\d{5}$/, // 港股 5 位数字（无前缀）
    /^HK\d{1,5}$/, // 港股 HK 前缀格式，如 HK00700、HK01810、HK1810
    /^\d{1,5}\.HK$/, // 港股 .HK 后缀格式，如 00700.HK、1810.HK
    /^[A-Z]{1,6}(\.[A-Z]{1,2})?$/, // 美股常见 Ticker
  ];

  const valid = patterns.some((regex) => regex.test(normalized));

  return {
    valid,
    message: valid ? undefined : '股票代码格式不正确',
    normalized,
  };
};
