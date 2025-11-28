<script setup>
import { PlayIcon, PauseIcon, ArrowPathIcon } from '@heroicons/vue/24/outline';

const props = defineProps({
  playing: { type: Boolean, default: true }
});

const emit = defineEmits(['play', 'pause', 'reload']);
</script>

<template>
  <div class="btn-row">
    <button
        class="btn primary"
        v-if="!playing"
        @click="emit('play')"
    >
      <span class="btn-icon">
        <PlayIcon />
      </span>
      Play
    </button>

    <button
        class="btn"
        v-else
        @click="emit('pause')"
    >
      <span class="btn-icon">
        <PauseIcon />
      </span>
      Pause
    </button>

    <button class="btn" @click="emit('reload')">
      <span class="btn-icon">
        <ArrowPathIcon />
      </span>
      Reload
    </button>
  </div>
</template>
