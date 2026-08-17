<script setup lang="ts">
import { Notivue, Notification, pastelTheme } from 'notivue'
import ThemeToggle from '@/components/ThemeToggle.vue'
</script>

<template>
  <Notivue v-slot="item">
    <Notification :item="item" :theme="pastelTheme" />
  </Notivue>
  <RouterView />
  <ThemeToggle />
</template>
