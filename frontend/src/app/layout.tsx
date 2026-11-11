import type { Metadata } from "next";
import "./globals.css";
import WorkspaceShell from "@/components/pic/WorkspaceShell";
import Providers from "@/components/Providers";

export const metadata: Metadata = {
  title: "AlphaHelion Purchasing Intelligence Cloud",
};

// One shell for the whole platform: the Purchasing Intelligence Cloud workspace and the Supplier Capability Digital Twin screens
// share the same sidebar, header and sign-in session.
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <Providers>
          <WorkspaceShell>{children}</WorkspaceShell>
        </Providers>
      </body>
    </html>
  );
}
