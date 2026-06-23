import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Toaster } from "@/components/ui/sonner";
import { OpenReplayTracker } from "@/components/OpenReplay";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const SITE_URL = (process.env.NEXT_PUBLIC_APP_URL || "https://llmwiki.app").replace(/\/$/, "");
const SITE_DESCRIPTION =
  "Open-source knowledge base that lets AI assistants turn raw sources into a maintained wiki.";

export const metadata: Metadata = {
  title: "LLM Wiki",
  description: SITE_DESCRIPTION,
  metadataBase: new URL(SITE_URL),
  openGraph: {
    title: "LLM Wiki",
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    siteName: "LLM Wiki",
    type: "website",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "LLM Wiki" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "LLM Wiki",
    description: SITE_DESCRIPTION,
    images: ["/og.png"],
  },
  // Signal to the LLM Wiki Chrome extension that this IS the wiki app — the
  // content script should bail out and let the in-app highlight UI run alone.
  // Works for the configured production host, dev (localhost), and future hosts.
  other: {
    "llmwiki-app": "true",
  },
};

// Script to prevent theme flash - runs before React hydrates
// Must match the storageKey used by ThemeProvider (default is 'theme')
const themeScript = `
  (function() {
    try {
      var storageKey = 'theme';
      var stored = localStorage.getItem(storageKey);
      var isValid = stored === 'light' || stored === 'dark';
      var theme = isValid ? stored : 'light';

      // Persist a sane default so a refresh doesn't fall back to light/system
      if (!isValid) {
        localStorage.setItem(storageKey, theme);
      }

      document.documentElement.classList.remove('light', 'dark');
      document.documentElement.classList.add(theme);
      document.documentElement.style.colorScheme = theme;
    } catch (e) {
      document.documentElement.classList.add('light');
      document.documentElement.style.colorScheme = 'dark';
    }
  })();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: themeScript }}
          suppressHydrationWarning
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
          disableTransitionOnChange
          storageKey="theme"
        >
          {children}
          <Toaster richColors />
          <OpenReplayTracker />
        </ThemeProvider>
      </body>
    </html>
  );
}
