export const formatNumber = (value: number | null | undefined) =>
  value == null ? "--" : new Intl.NumberFormat("zh-CN").format(value);

export const formatPercent = (
  value: number | undefined,
  total: number | undefined,
) =>
  value == null || !total ? "--" : `${((value / total) * 100).toFixed(2)}%`;
