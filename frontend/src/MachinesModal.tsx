import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip
} from '@mantine/core';
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';

import { KIND_COLOR, KIND_NAME, apiData, apiError, fieldErrors, plural } from './format';
import type { Machine, MachineKind } from './types';

interface Draft {
  id: number | null;
  name: string;
  kind: MachineKind;
  notes: string;
}

const EMPTY: Draft = { id: null, name: '', kind: 'laser', notes: '' };

/** Dialog: the machines of the workshop */
export function MachinesModal({
  context,
  slug,
  opened,
  canEdit,
  onClose,
  onChanged
}: Readonly<{
  context: InvenTreePluginContext;
  slug: string;
  opened: boolean;
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}>) {
  const api = useRef(context.api);
  api.current = context.api;

  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [removing, setRemoving] = useState<Machine | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!opened) {
      return;
    }

    let cancelled = false;

    setMachines(null);
    setDraft(null);
    setRemoving(null);
    setError(null);
    setErrors({});

    api.current
      .get(`/plugin/${slug}/machines/`)
      .then((response) => {
        if (!cancelled) {
          const found = apiData<{ machines: Machine[] }>(response, 'machines').machines;

          setMachines(found);

          // Nothing yet: start with the form
          if (found.length === 0 && canEdit) {
            setDraft(EMPTY);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setMachines([]);
          setError(apiError(err, 'Could not load the machines'));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [opened, slug, canEdit]);

  const finish = (response: any) => {
    setMachines(apiData<{ machines: Machine[] }>(response, 'machines').machines);
    setDraft(null);
    setRemoving(null);
    onChanged();
  };

  const save = () => {
    if (!draft) {
      return;
    }

    const body = { name: draft.name, kind: draft.kind, notes: draft.notes };

    setBusy(true);
    setError(null);
    setErrors({});

    (draft.id === null
      ? api.current.post(`/plugin/${slug}/machines/`, body)
      : api.current.put(`/plugin/${slug}/machines/${draft.id}/`, body)
    )
      .then(finish)
      .catch((err: any) => {
        const fields = fieldErrors(err);

        setErrors(fields);

        if (Object.keys(fields).every((key) => key === 'detail')) {
          setError(apiError(err, 'Could not save the machine'));
        }
      })
      .finally(() => setBusy(false));
  };

  const remove = (machine: Machine) => {
    setBusy(true);
    setError(null);

    api.current
      .delete(`/plugin/${slug}/machines/${machine.id}/`)
      .then(finish)
      .catch((err: any) => setError(apiError(err, 'Could not remove the machine')))
      .finally(() => setBusy(false));
  };

  return (
    <Modal opened={opened} onClose={onClose} title='Machines' centered size='lg'>
      <Stack gap='md'>
        <Text size='sm' c='dimmed'>
          Whatever makes parts in-house from a file: a laser cutter, a CNC mill. Each linked part
          belongs to one machine. Nothing is sent to a machine from here.
        </Text>

        {machines === null ? (
          <Center h={80}>
            <Loader size='sm' />
          </Center>
        ) : machines.length === 0 && !draft ? (
          <Text size='sm'>No machine has been added yet.</Text>
        ) : (
          <Stack gap='xs'>
            {machines.map((machine) => (
              <Paper withBorder p='sm' key={machine.id}>
                <Group justify='space-between' wrap='nowrap' align='flex-start'>
                  <Stack gap={2} style={{ minWidth: 0 }}>
                    <Group gap='xs'>
                      <Text fw={600}>{machine.name}</Text>
                      <Badge color={KIND_COLOR[machine.kind] ?? 'gray'} variant='light' radius='sm'>
                        {KIND_NAME[machine.kind] ?? 'Other'}
                      </Badge>
                      <Text size='sm' c='dimmed'>
                        {plural(machine.parts ?? 0, 'part')}
                      </Text>
                    </Group>
                    {machine.notes && (
                      <Text size='sm' style={{ whiteSpace: 'pre-wrap' }}>
                        {machine.notes}
                      </Text>
                    )}
                  </Stack>
                  {canEdit && (
                    <Group gap={4} wrap='nowrap'>
                      <Tooltip label='Edit'>
                        <ActionIcon
                          variant='subtle'
                          aria-label={`Edit ${machine.name}`}
                          onClick={() => {
                            setErrors({});
                            setError(null);
                            setRemoving(null);
                            setDraft({
                              id: machine.id,
                              name: machine.name,
                              kind: machine.kind,
                              notes: machine.notes ?? ''
                            });
                          }}
                        >
                          <IconPencil size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip
                        label={
                          (machine.parts ?? 0) > 0
                            ? 'Parts are linked to this machine. Move them or remove their links first.'
                            : 'Remove'
                        }
                      >
                        <ActionIcon
                          variant='subtle'
                          color='red'
                          aria-label={`Remove ${machine.name}`}
                          disabled={(machine.parts ?? 0) > 0}
                          onClick={() => {
                            setDraft(null);
                            setError(null);
                            setRemoving(machine);
                          }}
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  )}
                </Group>
              </Paper>
            ))}
          </Stack>
        )}

        {removing && (
          <Alert color='red' title={`Remove ${removing.name}?`}>
            <Stack gap='sm'>
              <Text size='sm'>Jobs which were made on it keep its name.</Text>
              <Group>
                <Button color='red' size='xs' loading={busy} onClick={() => remove(removing)}>
                  Remove the machine
                </Button>
                <Button variant='default' size='xs' onClick={() => setRemoving(null)}>
                  Keep it
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}

        {draft && (
          <Paper withBorder p='sm'>
            <Stack gap='sm'>
              <Text fw={600}>{draft.id === null ? 'New machine' : 'Edit machine'}</Text>
              <TextInput
                label='Name'
                placeholder='xTool S1, Makera Carvera, ...'
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.currentTarget.value })}
                error={errors.name}
                maxLength={60}
                data-autofocus
              />
              <Stack gap={4}>
                <Text size='sm' fw={500}>
                  Kind
                </Text>
                <SegmentedControl
                  aria-label='Kind'
                  data={[
                    { value: 'laser', label: 'Laser' },
                    { value: 'cnc', label: 'CNC' },
                    { value: 'other', label: 'Other' }
                  ]}
                  value={draft.kind}
                  onChange={(value) => setDraft({ ...draft, kind: value as MachineKind })}
                />
                {errors.kind && (
                  <Text size='xs' c='red'>
                    {errors.kind}
                  </Text>
                )}
              </Stack>
              <Textarea
                label='Notes'
                description='Shown with every part made on it: where it is, what is loaded, what to check first'
                placeholder='Optional'
                value={draft.notes}
                onChange={(event) => setDraft({ ...draft, notes: event.currentTarget.value })}
                error={errors.notes}
                autosize
                minRows={1}
                maxRows={4}
                maxLength={500}
              />
              <Group justify='flex-end'>
                <Button variant='default' onClick={() => setDraft(null)}>
                  Cancel
                </Button>
                <Button onClick={save} loading={busy} disabled={draft.name.trim() === ''}>
                  {draft.id === null ? 'Add the machine' : 'Save'}
                </Button>
              </Group>
            </Stack>
          </Paper>
        )}

        {error && <Alert color='red'>{error}</Alert>}

        {!draft && (
          <Group justify='space-between'>
            {canEdit ? (
              <Button
                variant='default'
                leftSection={<IconPlus size={16} />}
                onClick={() => {
                  setErrors({});
                  setError(null);
                  setRemoving(null);
                  setDraft(EMPTY);
                }}
              >
                Add a machine
              </Button>
            ) : (
              <Text size='sm' c='dimmed'>
                You need permission to change parts to manage the machines.
              </Text>
            )}
            <Button variant='default' onClick={onClose}>
              Close
            </Button>
          </Group>
        )}
      </Stack>
    </Modal>
  );
}
