import type { Metadata } from 'next';
import WorkspaceShell from '@/components/pic/WorkspaceShell';

export const metadata: Metadata = {
  title: 'Purchasing Intelligence Cloud',
};

export default function PicLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
