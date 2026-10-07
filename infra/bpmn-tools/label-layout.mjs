// Размеры относятся к новым схемам. Готовую DI, включая ручную геометрию, не меняем.
const TASK_WIDTH = 160
const TEXT_WIDTH = TASK_WIDTH - 28
const LINE_HEIGHT = 15

function textWidth(text) {
  return [...text].reduce((width, character) => width + (/[ЖШЩМW@]/u.test(character) ? 10 : 7), 0)
}

export function taskSize(name = '') {
  let lines = 0
  for (const paragraph of name.split('\n')) {
    let width = 0
    lines += 1
    for (const word of paragraph.split(/\s+/u).filter(Boolean)) {
      const size = textWidth(word)
      if (width && width + 7 + size > TEXT_WIDTH) {
        lines += 1
        width = 0
      }
      // Длинный непрерывный идентификатор также переносится bpmn-js по символам.
      lines += Math.max(0, Math.ceil(size / TEXT_WIDTH) - 1)
      width = (size % TEXT_WIDTH || TEXT_WIDTH) + (width ? width + 7 : 0)
    }
  }
  return { width: TASK_WIDTH, height: Math.max(80, lines * LINE_HEIGHT + 28) }
}

/** Расширяем сетку до размера подписей, сохраняя ортогональные маршруты раскладчика. */
export function fitTaskLabels(definitions) {
  for (const diagram of definitions.diagrams || []) {
    const elements = diagram.plane?.planeElement || []
    const shapes = elements.filter((element) => element.$type === 'bpmndi:BPMNShape')
    const tasks = shapes.filter((shape) => shape.bpmnElement?.$instanceOf('bpmn:Task'))
    if (!tasks.length) continue
    const sizes = new Map(tasks.map((shape) => [shape, taskSize(shape.bpmnElement.name)]))
    const scaleX = Math.max(1, ...tasks.map((shape) => sizes.get(shape).width / shape.bounds.width))
    const scaleY = Math.max(
      1,
      ...tasks.map((shape) => sizes.get(shape).height / shape.bounds.height),
    )
    const oldBounds = new Map(shapes.map((shape) => [shape.bpmnElement.id, { ...shape.bounds }]))
    for (const shape of shapes) {
      const bounds = shape.bounds
      const container = ['bpmn:Participant', 'bpmn:Lane', 'bpmn:SubProcess'].includes(
        shape.bpmnElement?.$type,
      )
      const size =
        sizes.get(shape) ||
        (container
          ? { width: bounds.width * scaleX, height: bounds.height * scaleY }
          : { width: bounds.width, height: bounds.height })
      bounds.x = (bounds.x + bounds.width / 2) * scaleX - size.width / 2
      bounds.y = (bounds.y + bounds.height / 2) * scaleY - size.height / 2
      bounds.width = size.width
      bounds.height = size.height
      if (shape.label?.bounds) scaleBounds(shape.label.bounds, scaleX, scaleY)
    }
    const newBounds = new Map(shapes.map((shape) => [shape.bpmnElement.id, shape.bounds]))
    for (const edge of elements.filter((element) => element.$type === 'bpmndi:BPMNEdge')) {
      const waypoints = edge.waypoint || []
      const original = waypoints.map((point) => ({ x: point.x, y: point.y }))
      waypoints.forEach((point) => {
        point.x *= scaleX
        point.y *= scaleY
      })
      for (const [index, endpoint] of [
        [0, 'sourceRef'],
        [waypoints.length - 1, 'targetRef'],
      ]) {
        const id = edge.bpmnElement?.[endpoint]?.id
        const before = oldBounds.get(id)
        const after = newBounds.get(id)
        if (!before || !after || !waypoints[index]) continue
        waypoints[index].x = after.x + ((original[index].x - before.x) / before.width) * after.width
        waypoints[index].y =
          after.y + ((original[index].y - before.y) / before.height) * after.height
      }
      if (edge.label?.bounds) scaleBounds(edge.label.bounds, scaleX, scaleY)
    }
  }
}

function scaleBounds(bounds, scaleX, scaleY) {
  bounds.x = (bounds.x + bounds.width / 2) * scaleX - bounds.width / 2
  bounds.y = (bounds.y + bounds.height / 2) * scaleY - bounds.height / 2
}
