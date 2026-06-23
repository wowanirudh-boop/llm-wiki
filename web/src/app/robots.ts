import type { MetadataRoute } from 'next'

const SITE_URL = (process.env.NEXT_PUBLIC_APP_URL || 'https://llmwiki.app').replace(/\/$/, '')

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: ['/api/', '/oauth/', '/callback'],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  }
}
