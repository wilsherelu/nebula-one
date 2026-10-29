import { useState } from 'react';
import { Button, Tag } from '@arco-design/web-react';
import { useI18n, type MessageKey } from '../../i18n';
import type { TemplateAccountingMethod, TemplateAccountingMethods, TemplateMethodCopyResult } from '../../api/templateMethods';
import { CopySchemeDialog } from './CopySchemeDialog';

const GROUP_ORDER = ['organization', 'cbam', 'product', 'user', 'other'] as const;
const GROUP_KEYS: Record<string, MessageKey> = {
  organization: 'tm.group.organization', cbam: 'tm.group.cbam',
  product: 'tm.group.product', user: 'tm.group.user', other: 'tm.group.other',
};
/** Fixed interface terms for the backend's purpose enum. Business names come from server data. */
const PURPOSE_KEYS: Record<string, MessageKey> = {
  organization_period_inventory: 'tm.purpose.organizationPeriod',
  organization_lifecycle_carbon: 'tm.purpose.organizationLifecycle',
  organization_ghg_inventory: 'tm.purpose.organizationGhg',
  cbam_trial: 'tm.purpose.cbamTrial',
  cbam_partial_review: 'tm.purpose.cbamPartialReview',
  product_carbon_footprint: 'tm.purpose.productFootprint',
  cbam: 'cm.purpose.cbam', organization: 'cm.purpose.organization',
  pcf: 'cm.purpose.pcf', custom: 'cm.purpose.custom',
};
const CHECK_KEYS: Record<string, MessageKey> = {
  ready: 'tm.check.ready', gap: 'tm.check.gap', draft: 'tm.check.draft',
  not_validated: 'tm.check.notValidated',
};

function SchemeCard({ scheme, lang, title, onOpen, onCopy }: {
  scheme: TemplateAccountingMethod; lang: string; title: string;
  onOpen: (scheme: TemplateAccountingMethod) => void;
  onCopy: (scheme: TemplateAccountingMethod, defaultName: string) => void;
}) {
  const { t } = useI18n();
  const purposeKey = PURPOSE_KEYS[scheme.purpose];
  const declared = scheme.display_name?.[lang]?.trim() || scheme.user_method?.name?.trim();
  const checkKey = CHECK_KEYS[scheme.check.status];
  const source = scheme.rule_source;
  const gaps = scheme.coverage_gaps;
  return <section className="section-panel template-scheme-card">
    <h3>{title}</h3>
    <div className="template-scheme-card__meta">
      <Tag size="small" color={scheme.origin === 'official_package' ? 'arcoblue' : 'green'}>
        {t(scheme.origin === 'official_package' ? 'tm.originOfficial' : 'tm.originUser')}
      </Tag>
      {purposeKey && declared ? <span>{t(purposeKey)}</span> : null}
      <span>{checkKey ? t(checkKey) : t('tm.check.unknown')}</span>
    </div>
    <p className="helper-text">
      {source.kind === 'none'
        ? t('tm.noPerFlowDeclaration')
        : t('tm.declaredCoverage', { declared: source.declared_count, ports: source.port_count })}
      {source.undeclared_port_count > 0 ? t('tm.undeclaredPorts', { count: source.undeclared_port_count }) : null}
    </p>
    {gaps.length ? <p className="helper-text template-scheme-card__gaps">{t('tm.gapCount', { count: gaps.length })}</p> : null}
    <div className="template-scheme-card__actions">
      <Button size="small" onClick={() => onOpen(scheme)}>{t(scheme.editable ? 'tm.openEditor' : 'tm.viewSource')}</Button>
      {scheme.actions.includes('copy_and_adjust') ? <Button size="small" type="primary"
        onClick={() => onCopy(scheme, `${title} · ${t('tm.copySuffix')}`)}>{t('tm.copyAction')}</Button> : null}
    </div>
    <details className="template-scheme-card__source">
      <summary>{t('tm.sourceDetail')}</summary>
      <dl>
        <dt>{t('tm.purposeRaw')}</dt>
        <dd><code>{scheme.purpose}</code></dd>
        <dt>{t('tm.checkStatusRaw')}</dt>
        <dd><code>{scheme.check.status}</code> · {scheme.check.status_basis}</dd>
        {scheme.base_method_ref ? <>
          <dt>{t('tm.basePackage')}</dt>
          <dd>{scheme.base_method_ref.package_id}@{scheme.base_method_ref.version}</dd>
          <dt>{t('tm.contentHash')}</dt>
          <dd><code>{scheme.base_method_ref.content_sha256}</code></dd>
        </> : null}
        {scheme.user_method ? <>
          <dt>{t('tm.userMethodIdentity')}</dt>
          <dd><code>{scheme.user_method.method_id}</code> v{scheme.user_method.version}</dd>
          <dt>{t('tm.contentHash')}</dt>
          <dd><code>{scheme.user_method.content_sha256}</code></dd>
        </> : null}
        {scheme.package_detail?.assurance_level ? <>
          <dt>{t('tm.assuranceLevel')}</dt>
          <dd>{scheme.package_detail.assurance_level}</dd>
        </> : null}
        {source.declared.length ? <>
          <dt>{t('tm.declaredExchanges')}</dt>
          <dd><ul>{source.declared.map(item => <li key={item.exchange_id}><code>{item.exchange_id}</code>
            <span className="helper-text">{item.rule_paths.join(' · ')}</span></li>)}</ul></dd>
        </> : null}
        {source.declared_but_absent_from_model.length ? <>
          <dt>{t('tm.declaredAbsent')}</dt>
          <dd>{source.declared_but_absent_from_model.map(id => <code key={id}>{id}</code>)}</dd>
        </> : null}
        {source.provenance.length ? <>
          <dt>{t('tm.provenance')}</dt>
          <dd><ul>{source.provenance.map((item, index) => <li key={`${item.source_path}-${index}`}>
            <span className="helper-text">{item.source_path}</span>
            {item.url ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.url}</a> : <span>{item.text}</span>}
          </li>)}</ul></dd>
        </> : null}
        {gaps.length ? <>
          <dt>{t('tm.gaps')}</dt>
          <dd><ul>{gaps.map((gap, index) => <li key={`${gap.code}-${index}`}>
            <code>{gap.code}</code>{gap.clause ? <span className="helper-text">{gap.clause}</span> : null}
            <span>{gap.message}</span>
            {gap.exchange_id ? <code>{gap.exchange_id}</code> : null}
          </li>)}</ul></dd>
        </> : null}
        {scheme.cbam_boundaries?.length ? <>
          <dt>{t('tm.frozenBoundaries')}</dt>
          <dd><ul>{scheme.cbam_boundaries.map(boundary => <li key={boundary.id}>
            {boundary.name} · {boundary.boundary_type} · {boundary.status}
            <span className="helper-text">{t('tm.boundaryCounts', {
              processes: boundary.included_process_count, rules: boundary.included_flow_rule_count,
              excluded: boundary.excluded_item_count })}</span>
          </li>)}</ul></dd>
        </> : null}
      </dl>
    </details>
  </section>;
}

export function MethodSchemePanel({ templateId, data, onOpen, onCopied }: {
  templateId: string;
  data: TemplateAccountingMethods;
  onOpen: (scheme: TemplateAccountingMethod) => void;
  onCopied: (result: TemplateMethodCopyResult) => void;
}) {
  const { t, lang } = useI18n();
  const [copying, setCopying] = useState<{ scheme: TemplateAccountingMethod; defaultName: string } | null>(null);
  const groups = GROUP_ORDER
    .map(group => ({ group, schemes: data.methods.filter(item => item.method_group === group) }))
    .filter(entry => entry.schemes.length > 0);
  const title = (scheme: TemplateAccountingMethod) => scheme.display_name?.[lang]?.trim()
    || scheme.user_method?.name?.trim()
    || (PURPOSE_KEYS[scheme.purpose] ? t(PURPOSE_KEYS[scheme.purpose]) : t('tm.unnamedScheme'));
  if (!data.methods.length) return <p className="helper-text">{t('tm.noSchemes')}</p>;
  return <div className="template-scheme-groups">
    {groups.map(({ group, schemes }) => <section key={group} className="template-scheme-group">
      <h2>{t(GROUP_KEYS[group])}</h2>
      <div className="template-library-grid">{schemes.map(scheme =>
        <SchemeCard key={scheme.method_key} scheme={scheme} lang={lang} title={title(scheme)}
          onOpen={onOpen} onCopy={(item, defaultName) => setCopying({ scheme: item, defaultName })} />)}</div>
    </section>)}
    {data.template.unresolved_method_package_refs.length ? <details className="template-scheme-card__source">
      <summary>{t('tm.unresolvedCount', { count: data.template.unresolved_method_package_refs.length })}</summary>
      <p className="helper-text">{t('tm.unresolvedRefs')}: <code>{data.template.unresolved_method_package_refs.join(', ')}</code></p>
    </details> : null}
    {copying ? <CopySchemeDialog key={copying.scheme.method_key} templateId={templateId}
      scheme={copying.scheme} defaultName={copying.defaultName}
      onClose={() => setCopying(null)}
      onCopied={result => { setCopying(null); onCopied(result); }} /> : null}
  </div>;
}
