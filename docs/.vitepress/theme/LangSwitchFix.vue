<!--
  Fixes two client-side navigation issues:

  1. The root path "/" redirects to the language matching the browser, with no
     version segment (each release line is deployed separately).
  2. The language switcher can produce mangled paths such as /zh/en/... —
     normalize them back to /en/...
-->
<script setup lang="ts">
import { useRoute, useRouter } from 'vitepress'
import { onMounted, ref } from 'vue'

const router = useRouter()
const route = useRoute()

let redirected = false

function detectLang(): string {
  if (typeof navigator === 'undefined') return 'en'
  const lang = (navigator.language || (navigator as any).userLanguage || 'en').toLowerCase()
  return lang.startsWith('zh') ? 'zh' : 'en'
}

function fixPath(path: string): string | null {
  const clean = path.replace(/\.html$/, '').replace(/\/$/, '') || '/'

  if (clean === '/') {
    return `/${detectLang()}/`
  }

  const mangled = clean.match(/^\/(zh|en)\/(zh|en)(\/.*)?$/)
  if (mangled) {
    return `/${mangled[2]}${mangled[3] || '/'}`
  }

  return null
}

onMounted(() => {
  if (redirected) return
  const target = fixPath(route.path)
  if (target) {
    redirected = true
    router.go(target)
  }
})
</script>
