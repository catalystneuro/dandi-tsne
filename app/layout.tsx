import type { Metadata } from "next";
import "./globals.css";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const base = new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://dandi-atlas.ben-dichter.chatgpt.site/");
const title = "DANDI Semantic Atlas";
const description = "An interactive semantic map of datasets in the DANDI Archive.";

export const metadata: Metadata = {
  metadataBase: base, title, description,
  icons: { icon: `${basePath}/favicon.svg`, shortcut: `${basePath}/favicon.svg` },
  openGraph: { title, description, type: "website", images: [{ url: new URL(`${basePath}/og.png`, base).toString(), width: 1536, height: 1024, alt: "DANDI Semantic Atlas semantic dataset map" }] },
  twitter: { card: "summary_large_image", title, description, images: [new URL(`${basePath}/og.png`, base).toString()] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
