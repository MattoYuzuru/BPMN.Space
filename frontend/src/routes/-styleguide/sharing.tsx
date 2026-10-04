import { useState } from 'react'
import type { ShareLink, ShareRole } from '@/entities/share'
import { useShareForm } from '@/features/share-project/model'
import {
  MemberRow,
  ShareCreateForm,
  ShareLinkResult,
  ShareLinkRow,
} from '@/features/share-project/share-parts'
import {
  Badge,
  Button,
  Card,
  Divider,
  EmptyState,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/shared/ui'
import { ShareStateBody } from '@/widgets/route-states/route-states'
import { InviteCard } from '@/widgets/share-page/invite-card'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

const link = (role: ShareRole, patch: Partial<ShareLink> = {}): ShareLink => ({
  id: `${role}-1`,
  role,
  created_at: '2026-09-28T09:00:00Z',
  expires_at: role === 'editor' ? '2026-10-12T09:00:00Z' : '2026-10-28T09:00:00Z',
  revoked_at: null,
  ...patch,
})

const member = {
  user_id: 'u-1',
  email: 'anna.petrova@company.ru',
  role: 'editor' as const,
  added_at: '2026-10-02T12:00:00Z',
}

/** Общий доступ: диалог «Поделиться», строки ссылок и участников, приглашение, публичный просмотр. */
export function SharingSection() {
  const form = useShareForm()
  const [result, setResult] = useState(true)
  return (
    <Section
      id="sharing"
      eyebrow="19 Общий доступ"
      title="Диалог доступа, приглашение, просмотр по ссылке"
      lead="Владелец делится проектом ссылкой: на просмотр без входа или приглашением редактора. Адрес показывается один раз — сразу после создания; дальше ссылку можно только отозвать."
    >
      <SpecimenGrid>
        <Specimen title="Новая ссылка" note="сроки зависят от роли">
          <div className="mx-auto w-full max-w-md">
            <ShareCreateForm
              role={form.role}
              days={form.days}
              onRoleChange={form.setRole}
              onDaysChange={form.setDays}
              onCreate={() => setResult(true)}
            />
          </div>
        </Specimen>
        <Specimen title="Ссылка создана" note="адрес один раз">
          <div className="mx-auto w-full max-w-md">
            {result ? (
              <ShareLinkResult
                url="https://architect.example/share/Q7x2-Lk9vR3mPz0aWc"
                access="viewer"
                expiresAt="2026-11-03T09:00:00Z"
                onAnother={() => setResult(false)}
              />
            ) : (
              <Button onClick={() => setResult(true)}>Показать снова</Button>
            )}
          </div>
        </Specimen>
      </SpecimenGrid>

      <SpecimenGrid>
        <Specimen title="Действующие ссылки и участники" note="вкладки со счётчиками">
          <Tabs defaultValue="links" className="mx-auto w-full max-w-md">
            <TabsList>
              <TabsTrigger value="links" count={2}>
                Ссылки
              </TabsTrigger>
              <TabsTrigger value="members" count={1}>
                Участники
              </TabsTrigger>
            </TabsList>
            <TabsContent value="links" className="pt-2">
              <ul className="flex flex-col divide-y divide-border">
                <ShareLinkRow link={link('viewer')} onRevoke={() => {}} />
                <ShareLinkRow link={link('editor')} onRevoke={() => {}} />
              </ul>
            </TabsContent>
            <TabsContent value="members" className="pt-2">
              <ul className="flex flex-col divide-y divide-border">
                <MemberRow member={member} onRemove={() => {}} />
              </ul>
            </TabsContent>
          </Tabs>
        </Specimen>
        <Specimen title="Пусто, загрузка, ошибка" canvas>
          <div className="flex flex-col gap-4">
            <Card padding="none">
              <EmptyState size="sm" backdrop="none" icon="link" title="Ссылок пока нет" />
            </Card>
            <Card padding="md" className="flex flex-col gap-3" aria-busy="true">
              <Skeleton className="h-9 rounded-md" />
              <Skeleton className="h-9 rounded-md" />
            </Card>
            <Card padding="none">
              <EmptyState
                size="sm"
                backdrop="none"
                icon="alert-circle"
                title="Список не загрузился"
                description="Нет связи с сервером. Проверьте подключение."
                action={<Button>Повторить</Button>}
              />
            </Card>
          </div>
        </Specimen>
      </SpecimenGrid>

      <Specimen title="Приглашение редактора" note="тот же язык, что у входа" canvas>
        <div className="grid gap-10 @4xl:grid-cols-3">
          <div>
            <Caption>Гость</Caption>
            <InviteCard state={{ kind: 'sign-in', token: 'demo' }} />
          </div>
          <div>
            <Caption>Вошедший</Caption>
            <InviteCard
              state={{
                kind: 'accept',
                title: 'Технологическое присоединение к электросетям',
                pending: false,
                onAccept: () => {},
              }}
            />
          </div>
          <div>
            <Caption>Доступ уже есть</Caption>
            <InviteCard
              state={{ kind: 'member', title: 'Закупка оборудования', projectId: 'demo' }}
            />
          </div>
        </div>
      </Specimen>

      <SpecimenGrid>
        <Specimen title="Просмотр по ссылке: шапка">
          <div className="flex flex-wrap items-center gap-3">
            <span className="type-subheading text-fg">Закупка оборудования</span>
            <Badge tone="neutral" variant="outline" icon="lock">
              Только просмотр
            </Badge>
            <Divider orientation="vertical" className="h-5" />
            <Button size="sm">Войти</Button>
          </div>
        </Specimen>
        <Specimen title="Ссылка не открылась" note="недействительна и срок истёк">
          <div className="grid gap-4 @2xl:grid-cols-2">
            <ShareStateBody kind="invalid" />
            <ShareStateBody kind="expired" />
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
