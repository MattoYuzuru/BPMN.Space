// Точечная правка bpmn-auto-layout 2.0.0-alpha.2: bbox-префильтр в проверке отрезков маршрутизации.
//
// Маршрутизация связей сверяет каждый кандидатный отрезок со всеми фигурами и всеми уже
// проложенными линиями. На графе 11 дорожек / 100 узлов / 126 потоков это ~21 с при таймауте
// 20 с. Префильтр точный: отрезок, чьи габариты не пересекают препятствие или другой отрезок,
// не может ни войти в него, ни пересечь, ни наложиться, поэтому раскладка побайтно та же
// (проверено на этом графе), а время — ~5,6 с. Скрипт идемпотентен и падает при любой
// другой версии или изменившемся коде: правку нужно пересмотреть при обновлении библиотеки.
//
// Запуск после `npm ci` (зависимости ставятся с --ignore-scripts): Dockerfile, `make setup`,
// `npm test` (так его получает и CI).
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const VERSION = '2.0.0-alpha.2'
const MARKER = 'BPMN Space: exact bounding-box prefilter'
// Пакет не экспортирует package.json: путь — от каталога сервиса.
const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'node_modules', 'bpmn-auto-layout')
const { version } = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
if (version !== VERSION) {
  throw new Error(
    `bpmn-auto-layout ${version}: правка рассчитана на ${VERSION}, пересмотрите patches/`,
  )
}

const ORIGINAL = `  const obstacles = shapes
    .filter(({ element }) => element !== sourceElement && element !== targetElement)
    .map(({ rect }) => inset(rect, obstacleInset));
  const connections = routedConnections.map(connection => {
    return {
      segments: toSegments(connection.points),
      sharedEndpoint: sharesEndpointChannel(
        connection.flow,
        sourceElement,
        targetElement
      )
    };
  });

  return (a, b) => {
    if (a.x === b.x && a.y === b.y) {
      return false;
    }

    if (obstacles.some(rect => segmentEntersRect(a, b, rect))) {
      return false;
    }

    return !connections.some(connection => {
      return connection.segments.some(([ c, d ]) => {
        return (!allowPerpendicularCrossings && segmentsProperlyCross(a, b, c, d)) ||
          (!connection.sharedEndpoint && collinearOverlap(a, b, c, d));
      });
    });
  };`

const PATCHED = `  const obstacles = shapes
    .filter(({ element }) => element !== sourceElement && element !== targetElement)
    .map(({ rect }) => inset(rect, obstacleInset));
  const connections = routedConnections.map(connection => {
    return {
      segments: toSegments(connection.points).map(([ c, d ]) => ({
        c,
        d,
        minX: Math.min(c.x, d.x),
        maxX: Math.max(c.x, d.x),
        minY: Math.min(c.y, d.y),
        maxY: Math.max(c.y, d.y)
      })),
      sharedEndpoint: sharesEndpointChannel(
        connection.flow,
        sourceElement,
        targetElement
      )
    };
  });

  return (a, b) => {
    if (a.x === b.x && a.y === b.y) {
      return false;
    }

    // BPMN Space: exact bounding-box prefilter. A segment whose box misses an obstacle or
    // another segment can neither enter, cross nor overlap it, so the result is unchanged.
    const minX = Math.min(a.x, b.x);
    const maxX = Math.max(a.x, b.x);
    const minY = Math.min(a.y, b.y);
    const maxY = Math.max(a.y, b.y);

    for (const rect of obstacles) {
      if (maxX < rect.x || minX > rect.x + rect.width || maxY < rect.y || minY > rect.y + rect.height) {
        continue;
      }

      if (segmentEntersRect(a, b, rect)) {
        return false;
      }
    }

    for (const connection of connections) {
      for (const segment of connection.segments) {
        if (maxX < segment.minX || minX > segment.maxX || maxY < segment.minY || minY > segment.maxY) {
          continue;
        }

        const { c, d } = segment;

        if ((!allowPerpendicularCrossings && segmentsProperlyCross(a, b, c, d)) ||
          (!connection.sharedEndpoint && collinearOverlap(a, b, c, d))) {
          return false;
        }
      }
    }

    return true;
  };`

const file = join(root, 'dist', 'index.js')
const source = await readFile(file, 'utf8')
// Сборка пакета — с CRLF: фрагменты приводятся к переводам строк файла.
const eol = source.includes('\r\n') ? '\r\n' : '\n'
const original = ORIGINAL.replaceAll('\n', eol)
const patched = PATCHED.replaceAll('\n', eol)
if (source.includes(MARKER)) {
  console.log('bpmn-auto-layout: правка маршрутизации уже применена')
} else if (source.split(original).length === 2) {
  await writeFile(file, source.replace(original, patched))
  console.log('bpmn-auto-layout: применена правка маршрутизации')
} else {
  throw new Error('bpmn-auto-layout: исходный фрагмент не найден, пересмотрите patches/')
}
