---
layout: page
title: NextBridge
---

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vitepress'

// Pick the language section matching the browser. Each release line is its own
// deployment, so paths never carry a version segment.
onMounted(() => {
  const lang = (navigator.language || 'en').toLowerCase()
  useRouter().go(lang.startsWith('zh') ? '/zh/' : '/en/')
})
</script>

<noscript>
<p>Redirecting... <a href="/en/">English</a> | <a href="/zh/">中文</a></p>
</noscript>
