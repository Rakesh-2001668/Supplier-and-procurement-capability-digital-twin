import type { Metadata } from "next";
import "./globals.css";
import Shell from "@/components/layout/Shell";
import Providers from "@/components/Providers";

export const metadata: Metadata = {
  title: "Supplier Capability Digital Twin",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
