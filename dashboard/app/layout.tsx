import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "car-tracker",
  description: "Chilean used-car market intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es-CL">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
