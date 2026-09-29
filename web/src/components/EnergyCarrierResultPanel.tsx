import { Alert, Table } from '@arco-design/web-react';
import type { EnergyCarrierResult, EnergyCarrierSeries } from '../api/types';
import { SankeyViewer } from './SankeyViewer';
import { StatusBadge } from './ui/StatusBadge';

function readableEnum(value: string): string {
  return value
    .split('_')
    .map((item) => `${item.slice(0, 1).toUpperCase()}${item.slice(1)}`)
    .join(' ');
}

export function EnergyCarrierResultPanel({ record }: { record: EnergyCarrierResult }) {
  return (
    <div className="energy-result">
      <div className="section-heading">
        <div>
          <h2>能源载体结果</h2>
          <p className="helper-text">不同单位身份和热值口径保持为独立序列，不跨序列求和。</p>
        </div>
        <StatusBadge status={record.result.status} />
      </div>
      {record.result.issues.length ? (
        <Alert
          type="warning"
          content={`该结果包含 ${record.result.issues.length} 条范围或换算警告，请在审计证据中核对。`}
        />
      ) : null}
      <Table<EnergyCarrierSeries>
        rowKey="series_id"
        pagination={false}
        scroll={{ x: 680 }}
        data={record.result.series}
        columns={[
          { title: '能源口径', width: 190, render: (_, item) => readableEnum(item.basis.energy_convention) },
          { title: '物料状态', width: 150, render: (_, item) => readableEnum(item.basis.material_condition) },
          { title: '条目', width: 80, align: 'right', render: (_, item) => item.entries.length },
          { title: '结果', width: 180, align: 'right', render: (_, item) => <span className="tabular">{item.total_amount}</span> },
          { title: '单位', width: 80, render: (_, item) => item.unit_symbol },
        ]}
      />
      <div className="energy-series-list">
        {record.result.series.map((series) => (
          <article className="energy-series-item" key={series.series_id}>
            <div><strong>{readableEnum(series.basis.energy_convention)}</strong><span>{readableEnum(series.basis.material_condition)}</span></div>
            <p className="tabular">{series.total_amount} <span>{series.unit_symbol}</span></p>
            <small>{series.entries.length} 条证据条目</small>
          </article>
        ))}
      </div>
      <SankeyViewer
        src={`/api/v1/energy-carrier-results/${record.id}/chart.svg`}
        alt="冻结能源载体结果图"
        helperText="各行代表独立证据序列；图形宽度不用于跨口径比较。"
        viewportLabel="能源载体结果图滚动区域"
        errorText="能源载体结果图加载失败，请核对持久化结果后重试。"
      />
    </div>
  );
}
