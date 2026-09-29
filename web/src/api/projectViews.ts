/** UI destinations for declared analysis contracts, not regulatory classifications. */
export function projectResultViews(capabilities: unknown): string[] | undefined {
  if (!Array.isArray(capabilities)) return undefined;
  return [
    ...(capabilities.includes('mfa.solved.v1') ? ['mfa'] : []),
    ...(capabilities.includes('pcf.product.v1') ? ['pcf'] : []),
    ...(capabilities.includes('organization.period.v1') ? ['organization-period'] : []),
    ...(capabilities.includes('organization.lifecycle-carbon.v1') ? ['organization-lifecycle'] : []),
    ...(capabilities.some(c => typeof c === 'string' && c.startsWith('cbam.')) ? ['cbam'] : []),
    ...(capabilities.includes('lcia.nebula.v1') ? ['lcia'] : []),
  ];
}
