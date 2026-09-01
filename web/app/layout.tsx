import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "fmtrader",
  description: "fmengine control and observability UI",
};

const NAV = [
  { href: "/", label: "Health" },
  { href: "/executions", label: "Executions" },
  { href: "/campaigns", label: "Campaigns" },
  { href: "/vault", label: "Vault" },
] as const;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="topnav">
            <span className="brand">fmtrader</span>
            <nav>
              {NAV.map((item) => (
                <Link key={item.href} href={item.href}>
                  {item.label}
                </Link>
              ))}
            </nav>
          </header>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
