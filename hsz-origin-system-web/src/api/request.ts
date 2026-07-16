import axios from 'axios'

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 10_000,
})

request.interceptors.request.use((config) => config)
request.interceptors.response.use((response) => response)

export default request
