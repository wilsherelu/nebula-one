import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {api, ApiError} from '../api/client';
import {seedProjectsApi, type MappedCandidates} from '../api/seedProjects';
import type {MappedBackgroundProcessPin, ProjectWorkspace} from '../api/types';
import {I18nProvider, LANGUAGE_STORAGE_KEY} from '../i18n';
import {MappedBackgroundDialog} from './MappedBackgroundDialog';

const pin: MappedBackgroundProcessPin = {
  schema_version: 'provider.mapped-background-process-pin.v1', consumer_exchange_id: 'steel::power',
  source_flow_namespace: 'tiangong_open_data', source_flow_uuid: 'synthetic', source_flow_version: '01.00.000',
  target_flow_uuid: 'synthetic-target', source_unit: 'MJ', target_unit: 'kWh', amount_factor: 1/3.6,
  mapping_level: 'L2', mapping_status: 'user_confirmed', mapping_rule_id: 'rule', mapping_package_id: 'test',
  mapping_package_version: '1.0.0', mapping_package_hash: 'a'.repeat(64), database_release: 'synthetic',
  process_uuid: 'provider', expected_process_content_hash: 'b'.repeat(64), expected_vector_checksum: 'c'.repeat(64),
  claim_role: 'partial_background_leaf',
};
const workspace: ProjectWorkspace = {
  application_id: 'steel', revision_id: 'r1', content_sha256: 'd'.repeat(64), template_title: 'Steel',
  fields: [{key: 'power', label: 'Power', process: 'Steel', value: 36, unit: 'MJ'}],
  demand: [{reference_flow_uuid: 'product', amount: 1000, unit: 'kg'}], source: 'test', saved: true,
  capabilities: [], blocked_capabilities: [], background_options: [], background_note: '',
};
const catalog: MappedCandidates = {
  consumer_exchange_id: 'steel::power', requires_confirmation: true,
  mapping: {package_hash: pin.mapping_package_hash, package_id: 'test', package_version: '1.0.0', mapping_level: 'L2',
    source_unit: 'MJ', target_unit: 'kWh', amount_factor: 1/3.6, mapping_reason: 'Synthetic mapping'},
  providers: [{process_uuid: 'provider', process_name: 'Synthetic provider', location: 'test', database_release: 'synthetic', executable: true}],
};
function mount(value = workspace, onReload = vi.fn()) {
  render(<I18nProvider><QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})}>
    <MappedBackgroundDialog workspace={value} consumerId="steel::power" onClose={vi.fn()} onSaved={vi.fn()} onReload={onReload} />
  </QueryClientProvider></I18nProvider>);
}
afterEach(() => {cleanup(); window.localStorage.removeItem(LANGUAGE_STORAGE_KEY); vi.restoreAllMocks();});

it('shows the local background choice in English without translating provider identity', async () => {
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, 'en');
  vi.spyOn(seedProjectsApi, 'mappedCandidates').mockResolvedValue(catalog);
  mount();
  expect(await screen.findByText('Synthetic provider')).toBeInTheDocument();
  expect(screen.getByText('Choose background data')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Confirm link'})).toBeDisabled();
});

it('requires L2 confirmation and saves exact pins with quantities and other mappings intact', async () => {
  vi.spyOn(seedProjectsApi, 'mappedCandidates').mockResolvedValue(catalog);
  const resolve = vi.spyOn(seedProjectsApi, 'resolveMapped').mockResolvedValue({pin, name: 'Synthetic provider'});
  const save = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue(workspace);
  const other = {...pin, consumer_exchange_id: 'steel::ore'};
  mount({...workspace, mapped_background_process_pins: [other]});
  fireEvent.click(await screen.findByRole('radio'));
  expect(screen.getByRole('button', {name: '确认关联'})).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', {name: '确认关联'}));
  await waitFor(() => expect(save).toHaveBeenCalledWith('steel', expect.objectContaining({
    revision_id: 'r1', values: {power: 36}, amounts: [1000], mapped_background_process_pins: [other, pin],
  }), 'zh'));
  expect(resolve).toHaveBeenCalledWith('steel', 'r1', expect.objectContaining({confirmed: true, expected_mapping_package_hash: pin.mapping_package_hash}));
});

it('never saves if the mapping has changed on the server', async () => {
  vi.spyOn(seedProjectsApi, 'mappedCandidates').mockResolvedValue({...catalog, requires_confirmation: false});
  vi.spyOn(seedProjectsApi, 'resolveMapped').mockRejectedValue(new Error('Mapping changed'));
  const save = vi.spyOn(api, 'saveProjectInputs');
  mount(); fireEvent.click(await screen.findByRole('radio'));
  fireEvent.click(screen.getByRole('button', {name: '确认关联'}));
  expect(await screen.findByText('Mapping changed')).toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
});

it('can remove an obsolete mapping even when its catalog is unavailable', async () => {
  vi.spyOn(seedProjectsApi, 'mappedCandidates').mockRejectedValue(new Error('Catalog unavailable'));
  const resolve = vi.spyOn(seedProjectsApi, 'resolveMapped');
  const save = vi.spyOn(api, 'saveProjectInputs').mockResolvedValue(workspace);
  mount({...workspace, mapped_background_process_pins: [pin]});
  fireEvent.click(screen.getByRole('button', {name: '移除此背景关联'}));
  await waitFor(() => expect(save).toHaveBeenCalledWith('steel', expect.objectContaining({mapped_background_process_pins: []}), 'zh'));
  expect(resolve).not.toHaveBeenCalled();
});

it.each(['PROJECT_MAPPING_UNAVAILABLE', 'PROJECT_BACKGROUND_MAPPING_REQUIRED'])('shows %s as an empty choice without enabling confirmation', async (code) => {
  vi.spyOn(seedProjectsApi, 'mappedCandidates').mockRejectedValue(new ApiError('No mapping', 422, code));
  const save = vi.spyOn(api, 'saveProjectInputs');
  mount();
  expect(await screen.findByText('暂无可关联的背景数据')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: '确认关联'})).toBeDisabled();
  expect(screen.queryByText('No mapping')).not.toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
});

it('offers a reload when the saved version moved under the binding', async () => {
  vi.spyOn(seedProjectsApi, 'mappedCandidates').mockResolvedValue(catalog);
  vi.spyOn(seedProjectsApi, 'resolveMapped').mockResolvedValue({pin, name: 'Synthetic provider'});
  const onReload = vi.fn();
  const save = vi.spyOn(api, 'saveProjectInputs').mockRejectedValue(new ApiError('数据版本已改变，请重新加载。', 409, 'PROJECT_INPUT_CONFLICT'));
  mount(workspace, onReload);
  fireEvent.click(await screen.findByRole('radio'));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', {name: '确认关联'}));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(await screen.findByText('数据版本已改变，请重新加载后再保存。')).toBeInTheDocument();
  expect(screen.getByRole('checkbox')).toBeChecked();
  fireEvent.click(screen.getByRole('button', {name: '重新加载'}));
  expect(onReload).toHaveBeenCalledOnce();
});
