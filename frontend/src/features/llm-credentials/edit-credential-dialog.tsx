import { useState } from 'react'
import {
  keyMask,
  LABEL_SEPARATOR,
  type LlmCredential,
  providerLabel,
  useUpdateLlmCredential,
} from '@/entities/llm-credential'
import { Button, Dialog, DialogContent, Field, Input, Switch } from '@/shared/ui'
import { ModelSelect } from './model-select'

/** Название, модель по умолчанию и признак «ключ по умолчанию». Сам ключ не меняется — только заменой. */
export function EditCredentialDialog({
  credential,
  onClose,
}: {
  credential: LlmCredential | null
  onClose: () => void
}) {
  return (
    <Dialog open={credential !== null} onOpenChange={(open) => !open && onClose()}>
      {credential && <EditForm key={credential.id} credential={credential} onClose={onClose} />}
    </Dialog>
  )
}

function EditForm({ credential, onClose }: { credential: LlmCredential; onClose: () => void }) {
  const update = useUpdateLlmCredential()
  const [label, setLabel] = useState(credential.label)
  const [model, setModel] = useState<string | null>(credential.default_model)
  const [isDefault, setIsDefault] = useState(credential.is_default)

  const save = () =>
    update.mutate(
      {
        id: credential.id,
        label: label.trim() || credential.label,
        default_model: model,
        is_default: isDefault,
      },
      { onSuccess: onClose },
    )

  return (
    <DialogContent
      title="Ключ"
      description={`${providerLabel(credential.provider)}${LABEL_SEPARATOR}${keyMask(credential.key_hint)}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button variant="primary" loading={update.isPending} onClick={save}>
            Сохранить
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Название">
          <Input
            name="label"
            autoComplete="off"
            maxLength={60}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </Field>
        <ModelSelect credential={credential} value={model} onChange={setModel} />
        <Switch
          label="Использовать по умолчанию"
          checked={isDefault}
          disabled={credential.is_default}
          onCheckedChange={setIsDefault}
        />
      </div>
    </DialogContent>
  )
}
