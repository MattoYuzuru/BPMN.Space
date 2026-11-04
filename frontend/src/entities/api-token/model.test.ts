import { agentClientSetups, agentGuideUrl, agentSetupMessage, mcpCommand, mcpUrl } from './model'

const MCP_URL = 'https://bpmn.example/mcp'
const SECRET = 'bps_secret'

describe('настройки подключения агента', () => {
  it('Claude Code совпадает с командой из ответа сервера', () => {
    const claude = agentClientSetups(MCP_URL, SECRET).find((item) => item.client === 'claude-code')
    expect(claude?.value).toBe(mcpCommand('https://bpmn.example', SECRET))
  })

  it('Cursor получает валидный JSON с заголовком Bearer', () => {
    const cursor = agentClientSetups(MCP_URL, SECRET).find((item) => item.client === 'cursor')
    expect(JSON.parse(cursor?.value ?? '')).toEqual({
      mcpServers: {
        'bpmn-space': { url: MCP_URL, headers: { Authorization: `Bearer ${SECRET}` } },
      },
    })
  })

  it('каждый клиент содержит адрес и токен', () => {
    for (const item of agentClientSetups(MCP_URL, SECRET)) {
      expect(item.value).toContain(MCP_URL)
      expect(item.value).toContain(SECRET)
    }
  })

  it('сообщение для агента ведёт на инструкцию того же сайта', () => {
    expect(agentGuideUrl('https://bpmn.example/')).toBe('https://bpmn.example/agents.md')
    const message = agentSetupMessage('https://bpmn.example', SECRET)
    expect(message).toContain('https://bpmn.example/agents.md')
    expect(message).toContain(mcpUrl('https://bpmn.example'))
    expect(message).toContain(SECRET)
  })
})
