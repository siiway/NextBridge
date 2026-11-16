<!--
  404 handler.

  This deployment serves a single release line at /en/* and /zh/*, so most old
  URLs are rewritten by `public/_redirects` before they reach the app. The
  client-side logic here only covers the leftovers:

  1. Legacy version-prefixed paths that slipped past the redirects
     (e.g. /en/v0.4/getting-started -> /en/getting-started).
  2. Mangled paths produced by the language switcher (/zh/en/... -> /en/...).
  3. Paths without a language prefix (e.g. /rules -> /en/rules).
  4. Anything already under /en or /zh is a real 404.
-->
<script setup lang="ts">
import { useData, useRoute, useRouter, withBase } from 'vitepress'
import { computed, onMounted, ref } from 'vue'

const router = useRouter()
const route = useRoute()
const { theme } = useData()

const redirecting = ref(false)

function detectLang(): string {
  if (typeof navigator === 'undefined') return 'en'
  const lang = (navigator.language || (navigator as any).userLanguage || 'en').toLowerCase()
  return lang.startsWith('zh') ? 'zh' : 'en'
}

function resolveTarget(rawPath: string): string | null {
  const cleanPath = rawPath.replace(/\.html$/, '')

  // Mangled language switcher paths: /zh/en/... or /en/zh/...
  const mangled = cleanPath.match(/^\/(zh|en)\/(zh|en)(\/.*)?$/)
  if (mangled) {
    return `/${mangled[2]}${mangled[3] || '/'}`
  }

  // Drop a legacy version segment if it survived the server-side redirects.
  const versioned = cleanPath.match(/^\/(en|zh)\/v\d+\.\d+(\/.*)?$/)
  if (versioned) {
    return `/${versioned[1]}${versioned[2] || '/'}`
  }

  // Already language-scoped without a version segment -> genuine 404.
  if (/^\/(en|zh)(\/|$)/.test(cleanPath)) return null

  // No language prefix -> detect from the browser.
  return `/${detectLang()}${cleanPath === '/' ? '/' : cleanPath}`
}

onMounted(() => {
  const target = resolveTarget(route.path)
  if (target) {
    redirecting.value = true
    router.go(target)
  }
})

const homeLink = computed(() => `/${detectLang()}/`)
</script>

<template>
  <div v-if="!redirecting" class="NotFound">
    <p class="code">{{ theme.notFound?.code ?? "404" }}</p>
    <h1 class="title">{{ theme.notFound?.title ?? "PAGE NOT FOUND" }}</h1>
    <div class="divider" />
    <blockquote class="quote">
      {{
        theme.notFound?.quote ??
        "But if you don't change your direction, and if you keep looking, you may end up where you are heading."
      }}
    </blockquote>

    <div class="action">
      <a
        class="link"
        :href="withBase(homeLink)"
        :aria-label="theme.notFound?.linkLabel ?? 'go to home'"
      >
        {{ theme.notFound?.linkText ?? "Take me home" }}
      </a>
    </div>
  </div>
</template>

<style scoped>
.NotFound {
  padding: 64px 24px 96px;
  text-align: center;
}

@media (min-width: 768px) {
  .NotFound {
    padding: 96px 32px 168px;
  }
}

.code {
  line-height: 64px;
  font-size: 64px;
  font-weight: 600;
}

.title {
  padding-top: 12px;
  letter-spacing: 2px;
  line-height: 20px;
  font-size: 20px;
  font-weight: 700;
}

.divider {
  margin: 24px auto 18px;
  width: 64px;
  height: 1px;
  background-color: var(--vp-c-divider);
}

.quote {
  margin: 0 auto;
  max-width: 256px;
  font-size: 14px;
  font-weight: 500;
  color: var(--vp-c-text-2);
}

.action {
  padding-top: 20px;
}

.link {
  display: inline-block;
  border: 1px solid var(--vp-c-brand-1);
  border-radius: 16px;
  padding: 3px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--vp-c-brand-1);
  transition:
    border-color 0.25s,
    color 0.25s;
}

.link:hover {
  border-color: var(--vp-c-brand-2);
  color: var(--vp-c-brand-2);
}
</style>
