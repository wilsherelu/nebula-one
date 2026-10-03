import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it } from 'vitest';
import type { ProjectWorkspace } from '../api/types';
import { ProcessInventoryTable } from './ProcessInventoryTable';

afterEach(cleanup);
it('distinguishes same-named flows with authored process descriptions instead of port IDs', () => {
  const fields = ['焦粉燃烧','碳酸盐分解'].map((description,index)=>({key:`key-${index}`, process_id:'process',port_id:`technical-port-${index}`,
    process:'烧结',label:'二氧化碳（化石源）',description,unit:'kg',value:1,group:'outputs'}));
  render(<MemoryRouter><ProcessInventoryTable fields={fields} values={{'key-0':1,'key-1':1}}
    disabled={false} onChange={()=>{}} workspace={{fields} as ProjectWorkspace} /></MemoryRouter>);
  expect(screen.getByText('焦粉燃烧')).toBeVisible();
  expect(screen.getByText('碳酸盐分解')).toBeVisible();
  expect(screen.queryByText('technical-port-0')).not.toBeInTheDocument();
});
