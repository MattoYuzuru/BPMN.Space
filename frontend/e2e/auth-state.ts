import { fileURLToPath } from 'node:url'

/** Файл с cookie вошедшего тестового пользователя (создаёт global-setup, в git не попадает). */
export const AUTH_STATE = fileURLToPath(new URL('./.auth/state.json', import.meta.url))
