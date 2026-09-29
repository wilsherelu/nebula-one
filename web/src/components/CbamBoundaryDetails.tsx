import { Alert } from '@arco-design/web-react';
import type { CbamTrialResult } from '../api/types';
import { useI18n } from '../i18n';

/** Render the server's classifications and units; no inferred regulatory mappings or totals. */
export function CbamBoundaryDetails({ result }: { result: CbamTrialResult }) {
  const { t } = useI18n();
  const indirect = result.attributed_emissions.indirect;
  const rows = result.coverage?.exchanges ?? [];
  return <div className="cbam-boundary-details">
    {indirect ? <Alert type="info" title={t('cbam.indirect')} content={<>
      {indirect.activity ? <p>{t('cbam.recordedElectricity', { amount: indirect.activity.value, unit: indirect.activity.unit })}</p> : null}
      <p>{indirect.value === null ? t('cbam.noZero') : `${indirect.value} ${indirect.unit ?? ''}`}</p>
      {indirect.missing_factor_package ? <p>{t('cbam.factorPackageNeeded', { ref: indirect.missing_factor_package })}</p> : null}
    </>} /> : null}
    {result.nitrogen_basis?.applies ? <dl className="pcf-result__facts">
      <div><dt>{result.nitrogen_basis.label}</dt><dd>{result.nitrogen_basis.value} {result.nitrogen_basis.unit}</dd></div>
    </dl> : null}
    {rows.length ? <div className="cbam-boundary-details__scroll" role="region" aria-label={t('cbam.exchangeDetails')} tabIndex={0}>
      <table>
        <caption>{t('cbam.exchangeCaption')}</caption>
        <thead><tr><th>{t('cbam.processExchange')}</th><th>{t('cbam.classification')}</th><th>{t('cbam.exchangeAmount')}</th><th>{t('cbam.clauseBasis')}</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={`${row.process_uuid}:${row.exchange_id}`}>
          <td><small>{row.process_uuid}</small><br />{row.exchange_id}</td>
          <td>{row.disposition}</td>
          <td>{row.amount === null ? t('cbam.noSolvedAmount') : `${row.amount} ${row.unit}`}</td>
          <td>{row.clause}<br />{row.basis}</td>
        </tr>)}</tbody>
      </table>
    </div> : <p>{t('cbam.noExchangeDetails')}</p>}
  </div>;
}
