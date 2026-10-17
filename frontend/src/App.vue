<template>
  <div class="layout">
    <aside class="sidebar">
      <h1 class="brand">{{ t('app.title') }}</h1>
      <nav>
        <router-link to="/" exact-active-class="active">{{ t('nav.overview') }}</router-link>
        <router-link to="/concept" active-class="active">{{ t('nav.concept') }}</router-link>
        <router-link to="/instance" active-class="active">{{ t('nav.instance') }}</router-link>
        <router-link to="/extract" active-class="active">{{ t('nav.extract') }}</router-link>
        <router-link to="/text-sources" active-class="active">{{ t('nav.textSources') }}</router-link>
        <router-link to="/qa" active-class="active">{{ t('nav.qa') }}</router-link>
        <router-link to="/reasoning" active-class="active">{{ t('nav.reasoning') }}</router-link>
        <router-link to="/function" active-class="active">{{ t('nav.function') }}</router-link>
        <router-link to="/rules" active-class="active">{{ t('nav.rules') }}</router-link>
      </nav>
      <div class="footer">
        <button class="lang-btn" :title="t('app.lang.switch')" @click="toggleLang">
          🌐 {{ locale === 'zh' ? t('app.lang.en') : t('app.lang.zh') }}
        </button>
        <p>MySQL → Neo4j</p>
        <p>Vue 3 · D3 · Flask</p>
      </div>
    </aside>
    <main class="main">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { t, setLocale, locale } from './i18n.js'

function toggleLang() {
  setLocale(locale.value === 'zh' ? 'en' : 'zh')
}
</script>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
}
.sidebar {
  width: 220px;
  background: #111827;
  color: #f3f4f6;
  display: flex;
  flex-direction: column;
  padding: 20px 16px;
}
.brand {
  font-size: 18px;
  margin-bottom: 24px;
  letter-spacing: 1px;
}
nav { display: flex; flex-direction: column; gap: 4px; }
nav a {
  padding: 10px 12px;
  border-radius: 6px;
  color: #d1d5db;
  font-size: 14px;
}
nav a:hover { background: #1f2937; color: #fff; }
nav a.active { background: #2563eb; color: #fff; }
.footer {
  margin-top: auto;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.6;
}
.lang-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  padding: 6px 12px;
  font-size: 12px;
  color: #d1d5db;
  background: #1f2937;
  border: 1px solid #374151;
  border-radius: 6px;
}
.lang-btn:hover {
  color: #fff;
  background: #2563eb;
  border-color: #2563eb;
}
.main {
  flex: 1;
  min-width: 0;
  overflow: auto;
  padding: 24px;
}
</style>
