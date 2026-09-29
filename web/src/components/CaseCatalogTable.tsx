import { Button, Empty, Input, Table, Tag, Tooltip } from '@arco-design/web-react';
import { IconSearch } from '@arco-design/web-react/icon';
import { useState } from 'react';
import type { Application, CasePackApplication, CasePackCatalogItem } from '../api/types';

export function caseDemandLabel(applicationCase: CasePackApplication): string {
  const demand = applicationCase.demand[0];
  if (!demand || typeof demand.amount !== 'number' || !demand.unit) return '需求未解析';
  return `${new Intl.NumberFormat('zh-CN').format(demand.amount)} ${demand.unit}`;
}

export function matchCaseApplication(pack: CasePackCatalogItem, item: CasePackApplication, applications: Application[]) {
  return applications.find((application) => application.context.case_pack_id === pack.id
    && !application.context.project_key
    && application.context.resolved_case_sha256 === item.resolved_case_sha256);
}

interface Props {
  pack: CasePackCatalogItem;
  applications: Application[];
  checking: boolean;
  unavailable: boolean;
  pending: boolean;
  selectedCaseId: string;
  onDetails: (id: string) => void;
  onOpen: (item: CasePackApplication, application: Application | undefined) => void;
}

export function CaseCatalogTable({ pack, applications, checking, unavailable, pending, selectedCaseId, onDetails, onOpen }: Props) {
  const [query, setQuery] = useState('');
  const items = pack.applications.filter((item) => item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <>
    <div className="catalog-toolbar">
      <span className="catalog-toolbar__count">应用案例 <span className="helper-text">{items.length} 项</span></span>
      <Input aria-label="搜索案例" placeholder="搜索案例名称" prefix={<IconSearch />} allowClear value={query} onChange={setQuery} />
    </div>
    <Table<CasePackApplication>
      className="catalog-table"
      rowKey="id"
      data={items}
      pagination={false}
      border={false}
      scroll={{ x: 760 }}
      rowClassName={(item) => item.id === selectedCaseId ? 'catalog-table__selected' : ''}
      noDataElement={<Empty description="没有匹配的案例" />}
      columns={[
        { title: '案例名称', dataIndex: 'title', width: 320, render: (title: string, item) => <Tooltip content={title} trigger={['hover', 'focus']}><button type="button" className="catalog-record-name" disabled={pending} onClick={() => onDetails(item.id)}>{title}</button></Tooltip> },
        { title: '核算规模', width: 150, align: 'right', render: (_, item) => <span className="tabular">{caseDemandLabel(item)}</span> },
        { title: '分析状态', width: 130, render: (_, item) => checking ? <span className="helper-text">正在核对</span> : unavailable ? <Tag color="orange">核对失败</Tag> : matchCaseApplication(pack, item, applications) ? <Tag color="green">已创建</Tag> : <span className="helper-text">未创建</span> },
        { title: '操作', width: 160, fixed: 'right', align: 'right', render: (_, item) => {
          const application = matchCaseApplication(pack, item, applications);
          return <div className="catalog-row-actions">
            <Button type="text" size="small" disabled={pending} onClick={() => onDetails(item.id)}>详情</Button>
            <Button type="text" size="small" disabled={checking || unavailable || pending} onClick={() => onOpen(item, application)}>{application ? '进入分析' : '使用案例'}</Button>
          </div>;
        } },
      ]}
    />
  </>;
}
