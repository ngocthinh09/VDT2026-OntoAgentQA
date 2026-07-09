import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OntoAgentQA Demo",
  description: "Vietnamese Knowledge Graph question answering demo with traceable tool execution.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
