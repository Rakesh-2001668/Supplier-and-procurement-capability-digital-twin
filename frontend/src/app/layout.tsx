import type { Metadata, Viewport } from "next";
import "./globals.css";
import WorkspaceShell from "@/components/pic/WorkspaceShell";
import Providers from "@/components/Providers";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "AlphaHelion Purchasing Intelligence Cloud",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6fb" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1120" },
  ],
};

// One shell for the whole platform: the Purchasing Intelligence Cloud workspace and the Supplier Capability Digital Twin screens
// share the same sidebar, header and sign-in session.
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // data-theme is set before the first paint by the boot script, so React must not complain that it differs.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="antialiased">
        <Providers>
          <WorkspaceShell>{children}</WorkspaceShell>
        </Providers>
      </body>
    </html>
  );
}
