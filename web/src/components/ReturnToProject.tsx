import { Button } from '@arco-design/web-react';
import { IconArrowLeft } from '@arco-design/web-react/icon';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n';

export function ReturnToProject({ applicationId }: { applicationId: string }) {
  const navigate = useNavigate();
  const { t } = useI18n();
  return <Button className="return-project-button" type="secondary" icon={<IconArrowLeft />}
    onClick={() => navigate(`/applications/${applicationId}/workbench`)}>{t('analysis.backToProject')}</Button>;
}
