import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Purchasing Intelligence Cloud',
};

// The platform shell (sidebar, header, live updates) comes from the root layout and is shared with the twin screens.
export default function PicLayout({ children }: { children: React.ReactNode }) {
  return children;
}
