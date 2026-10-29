import { useState } from 'react';
import { Button, Select } from '@arco-design/web-react';
import { useI18n, type MessageKey } from '../../i18n';
import type {
  TemplateAccountingMethod, TemplateAccountingMethods, TemplateAccountingTask, TemplateMethodCopyResult,
} from '../../api/templateMethods';
import { CopySchemeDialog } from './CopySchemeDialog';

// The rules tab declares only real accounting rules. The default LCIA (complete_model) is a
// calculation setting shown under 模型与数据, and the project entry runs it with no rule, so it
// is never a rule card here (plan v3 §1 negates a PCF card living in the rules tab). The role keys
// below stay total for the Record type, but only TASK_ORDER's roles are ever rendered.
const TASK_ORDER: TemplateAccountingTask['role'][] = ['cbam', 'scope_classification'];
const TASK_TITLE: Record<TemplateAccountingTask['role'], MessageKey> = {
  complete_model: 'tm.task.completeModel', cbam: 'tm.task.cbam', scope_classification: 'tm.task.scopeClassification',
};
const TASK_HINT: Record<TemplateAccountingTask['role'], MessageKey> = {
  complete_model: 'tm.task.completeModelHint', cbam: 'tm.task.cbamHint', scope_classification: 'tm.task.scopeHint',
};
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

function schemeTitle(scheme: TemplateAccountingMethod, lang: string, t: (key: MessageKey) => string): string {
  return scheme.display_name?.[lang]?.trim()
    || scheme.user_method?.name?.trim()
    || (PURPOSE_KEYS[scheme.purpose] ? t(PURPOSE_KEYS[scheme.purpose]) : t('tm.unnamedScheme'));
}

/** One compact rule row: a single current preset, its selector, and the rule's own forward action. */
function TaskRow({ task, data, lang, selectedKey, onSelectKey, onOpen, onCopy }: {
  task: TemplateAccountingTask; data: TemplateAccountingMethods; lang: string; selectedKey: string;
  onSelectKey: (key: string) => void;
  onOpen: (scheme: TemplateAccountingMethod) => void;
  onCopy: (scheme: TemplateAccountingMethod, defaultName: string) => void;
}) {
  const { t } = useI18n();
  const byKey = new Map(data.methods.map(method => [method.method_key, method]));
  const memberKeys = [...task.preset_keys, ...task.user_scheme_keys.filter(key => !task.preset_keys.includes(key))];
  const members = memberKeys.map(key => byKey.get(key)).filter((item): item is TemplateAccountingMethod => Boolean(item));
  const current = byKey.get(selectedKey) ?? members[0];
  const options = members.map(scheme => ({
    value: scheme.method_key,
    label: `${schemeTitle(scheme, lang, t)}${scheme.origin === 'official_package' ? '' : ` · ${t('tm.originUser')}`}`,
  }));
  const directRef = current?.package_detail?.formula_graph.source_direct_method as
    { reference?: string; content_sha256?: string } | undefined;
  const directScheme = directRef ? data.methods.find(item => item.base_method_ref
    && `${item.base_method_ref.package_id}@${item.base_method_ref.version}` === directRef.reference
    && item.base_method_ref.content_sha256 === directRef.content_sha256) : undefined;
  const source = (directScheme ?? current)?.rule_source;
  const forward = () => {
    if (!current) return;
    if (current.user_method?.method_id) onOpen(current);
    else {
      const editableSource = directScheme ?? current;
      onCopy(editableSource, `${schemeTitle(editableSource, lang, t)} · ${t('tm.copySuffix')}`);
    }
  };
  return <article className="template-task-row">
    <div className="template-task-row__head">
      <h2>{t(TASK_TITLE[task.role])}</h2>
      <p className="helper-text">{t(TASK_HINT[task.role])}</p>
    </div>
    {options.length ? <label className="template-task-row__choice"><span>{t('tm.task.currentPreset')}</span>
      <Select className="template-task-row__select" aria-label={t('tm.task.currentPreset')}
        value={current?.method_key} options={options} onChange={onSelectKey} />
    </label> : null}
    {current ? <details className="template-task-row__description"><summary>{t('tm.schemeExplanation')}</summary>
      {directRef ? <p className="helper-text">{t('tm.task.directComponentHint')}</p> : null}
      <p className="helper-text template-task-row__coverage">
      {source && source.kind !== 'none'
        ? t('tm.declaredCoverage', { declared: source.declared_count, ports: source.port_count })
        : t('tm.noPerFlowDeclaration')}
    </p></details> : <p className="helper-text">{t('tm.task.noPreset')}</p>}
    <div className="template-task-row__actions">
      {current ? <Button type="outline" onClick={forward}
        disabled={members.length === 0 || Boolean(directRef && !directScheme)}>
        {t(directRef ? 'tm.task.adjustDirect' : 'tm.task.viewAndAdjust')}</Button> : null}
    </div>
  </article>;
}

/** The 核算设置 first screen when the template version binds a task-declaring scheme set: three
 * compact task rows, then the reader's other custom schemes. User copies live inside their own
 * task's selector and are never re-shown beside the official presets. */
export function MethodTaskPanel({ templateId, data, onOpen, onCopied, onCreateScheme }: {
  templateId: string;
  data: TemplateAccountingMethods;
  onOpen: (scheme: TemplateAccountingMethod) => void;
  onCopied: (result: TemplateMethodCopyResult) => void;
  onCreateScheme: () => void;
}) {
  const { t, lang } = useI18n();
  const tasks = data.tasks ?? [];
  const byKey = new Map(data.methods.map(method => [method.method_key, method]));
  const [selected, setSelected] = useState<Record<string, string>>(() => Object.fromEntries(
    tasks.map(task => [task.role, task.preset_keys[0] ?? task.user_scheme_keys[0] ?? ''])));
  const [copying, setCopying] = useState<{ scheme: TemplateAccountingMethod; defaultName: string } | null>(null);
  const ordered = TASK_ORDER
    .map(role => tasks.find(task => task.role === role))
    .filter((task): task is TemplateAccountingTask => Boolean(task));
  const otherSchemes = data.other_scheme_keys
    .map(key => byKey.get(key)).filter((item): item is TemplateAccountingMethod => Boolean(item));
  const selectKey = (role: string) => (key: string) => setSelected(previous => ({ ...previous, [role]: key }));

  return <div className="template-task-list">
    {ordered.map(task => <TaskRow key={task.role} task={task} data={data} lang={lang}
      selectedKey={selected[task.role] ?? ''} onSelectKey={selectKey(task.role)}
      onOpen={onOpen}
      onCopy={(scheme, defaultName) => setCopying({ scheme, defaultName })} />)}
    <section className="template-other-schemes">
      <div className="template-other-schemes__head"><h2>{t('tm.otherSchemes')}</h2>
        <Button onClick={onCreateScheme}>{t('tm.newScheme')}</Button></div>
      {otherSchemes.length ? <ul className="template-other-schemes__list">
        {otherSchemes.map(scheme => <li key={scheme.method_key}>
          <span>{schemeTitle(scheme, lang, t)}</span>
          <Button size="small" type="text" onClick={() => onOpen(scheme)}>{t('tm.openEditor')}</Button>
        </li>)}
      </ul> : <p className="helper-text">{t('tm.noOtherSchemes')}</p>}
    </section>
    {copying ? <CopySchemeDialog key={copying.scheme.method_key} templateId={templateId}
      scheme={copying.scheme} defaultName={copying.defaultName}
      onClose={() => setCopying(null)}
      onCopied={result => { setCopying(null); onCopied(result); }} /> : null}
  </div>;
}
