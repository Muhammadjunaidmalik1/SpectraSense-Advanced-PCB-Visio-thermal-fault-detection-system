<script setup>
import { ref, computed } from 'vue';
import { RouterView, RouterLink, useRoute } from 'vue-router';
import {
  Bars3Icon,
  ChevronDoubleLeftIcon,
  VideoCameraIcon,
  ArchiveBoxIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline';

const isSidebarCollapsed = ref(false);
const route = useRoute();

const currentTitle = computed(() => route.meta.title || 'Live View');

function toggleSidebar() {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
}
</script>


<template>
  <div class="app-layout" :class="{ 'sidebar-collapsed': isSidebarCollapsed }">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <button
            class="sidebar-toggle"
            @click="toggleSidebar"
            aria-label="Toggle navigation"
        >
          <Bars3Icon v-if="isSidebarCollapsed" class="w-4 h-4" />
          <ChevronDoubleLeftIcon v-else class="w-4 h-4" />
        </button>
        <span v-if="!isSidebarCollapsed" class="sidebar-title">SolderCam</span>
      </div>

      <nav class="sidebar-nav">
        <RouterLink to="/" class="nav-link" active-class="nav-link-active">
          <span class="nav-icon">
            <VideoCameraIcon />
          </span>
          <span v-if="!isSidebarCollapsed" class="nav-label">Live</span>
        </RouterLink>

        <RouterLink to="/archive" class="nav-link" active-class="nav-link-active">
          <span class="nav-icon">
            <ArchiveBoxIcon />
          </span>
          <span v-if="!isSidebarCollapsed" class="nav-label">Archive</span>
        </RouterLink>

        <RouterLink to="/settings" class="nav-link" active-class="nav-link-active">
          <span class="nav-icon">
            <Cog6ToothIcon />
          </span>
          <span v-if="!isSidebarCollapsed" class="nav-label">Settings</span>
        </RouterLink>
      </nav>
    </aside>

    <!-- Main shell -->
    <div class="app-shell">
      <header class="app-header">
        <div class="app-header-main">
          <div>
            <div class="app-header-title">Soldering Station Monitor</div>
            <div class="text-muted">{{ currentTitle }}</div>
          </div>
        </div>
      </header>

      <main class="app-main">
        <RouterView />
      </main>

      <footer class="app-footer">
        <span>Tip:</span>
        <span>
          If the stream does not display, your camera may require login, HTTPS, or a specific
          stream URL (e.g. an MJPEG or HLS endpoint).
        </span>
      </footer>
    </div>
  </div>
</template>
