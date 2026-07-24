import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Technical Reference | JUNCA Social Ecosystem Chain",
  description:
    "Institutional technical reference for JUNCA Social Ecosystem Chain protocol architecture, asset standards, Ethereum/ERC, BSC and TRON interoperability, governance, security and release evidence.",
  keywords: [
    "JUNCA Social Ecosystem Chain",
    "partner adoption",
    "token issuance",
    "NFT issuance",
    "Ethereum ERC interoperability",
    "BSC Testnet interoperability",
    "TRON Shasta interoperability",
    "DApp development",
    "institutional governance",
  ],
  robots: {
    index: false,
    follow: false,
  },
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
