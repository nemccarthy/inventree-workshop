import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  FileButton,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconTrash, IconUpload, IconX } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';

import { MachinesModal } from './MachinesModal';
import { apiData, apiError, fieldErrors, fmtBytes, fmtDate, fmtMinutes, fmtQty } from './format';
import type { AttachedFile, FileDetail, Link, Machine, PartLabel } from './types';
import { FileDetails, LocationSelect, Preview } from './ui';

interface Chosen {
  attachment: number;
  label: string;
}

function asNumber(value: number | string): number | null {
  if (value === '' || value === null || value === undefined) {
    return null;
  }

  const number = typeof value === 'number' ? value : Number(value);

  return Number.isNaN(number) ? null : number;
}

/** Dialog: link a part to the machine which makes it, and to its files */
export function LinkModal({
  context,
  slug,
  part,
  link,
  canManageMachines,
  opened,
  onClose,
  onSaved
}: Readonly<{
  context: InvenTreePluginContext;
  slug: string;
  part: PartLabel;
  link: Link | null;
  canManageMachines: boolean;
  opened: boolean;
  onClose: () => void;
  onSaved: () => void;
}>) {
  const api = useRef(context.api);
  api.current = context.api;

  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [machinesKey, setMachinesKey] = useState(0);
  const [managing, setManaging] = useState(false);
  const [machine, setMachine] = useState<number | null>(null);

  const [attached, setAttached] = useState<AttachedFile[] | null>(null);
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [details, setDetails] = useState<Record<number, FileDetail>>({});
  const [uploading, setUploading] = useState(false);

  const [perRun, setPerRun] = useState<number | string>('');
  const [perRunEdited, setPerRunEdited] = useState(false);
  const [minutes, setMinutes] = useState<number | string>('');
  const [minutesEdited, setMinutesEdited] = useState(false);
  const [restockTo, setRestockTo] = useState<number | string>('');
  const [destination, setDestination] = useState<number | null>(null);
  const [setupNotes, setSetupNotes] = useState('');

  const [busy, setBusy] = useState<'save' | 'remove' | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const resetUpload = useRef<() => void>(null);

  // What the dialog starts from, read only when it opens
  const initial = useRef(link);
  initial.current = link;

  useEffect(() => {
    if (!opened) {
      return;
    }

    const current = initial.current;
    let cancelled = false;

    setAttached(null);
    setDetails({});
    setChosen(
      (current?.files ?? [])
        .filter((file) => !file.missing)
        .map((file) => ({ attachment: file.attachment, label: file.label ?? '' }))
    );
    setMachine(current && !current.machine_missing ? current.machine : null);
    setPerRun(current ? current.parts_per_run : '');
    setPerRunEdited(Boolean(current));
    setMinutes(current?.run_minutes ?? '');
    setMinutesEdited(Boolean(current));
    setRestockTo(current?.restock_to ?? '');
    setDestination(current?.destination ?? null);
    setSetupNotes(current?.setup_notes ?? '');
    setError(null);
    setErrors({});
    setConfirmRemove(false);

    api.current
      .get(`/plugin/${slug}/part/${part.pk}/files/`)
      .then((response) => {
        if (cancelled) {
          return;
        }

        const found = apiData<{ files: AttachedFile[] }>(response, 'files').files;

        setAttached(found);

        // A part with one machine file attached: that will be the one
        if (!current) {
          const known = found.filter((entry) => entry.kind !== '');

          if (known.length === 1) {
            setChosen([{ attachment: known[0].attachment, label: '' }]);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setAttached([]);
          setError(apiError(err, 'Could not load the files of the part'));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [opened, slug, part.pk]);

  // The machines: when the dialog opens, and again after they were managed
  useEffect(() => {
    if (!opened) {
      return;
    }

    let cancelled = false;

    api.current
      .get(`/plugin/${slug}/machines/`)
      .then((response) => {
        if (cancelled) {
          return;
        }

        const found = apiData<{ machines: Machine[] }>(response, 'machines').machines;

        setMachines(found);

        // With a single machine there is nothing to choose
        setMachine((value) =>
          value === null && found.length === 1 && !initial.current ? found[0].id : value
        );
      })
      .catch(() => {
        if (!cancelled) {
          setMachines([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [opened, slug, machinesKey]);

  // Read each chosen file once
  const wanted = chosen.map((entry) => entry.attachment).join(',');

  useEffect(() => {
    if (!opened) {
      return;
    }

    let cancelled = false;

    for (const entry of chosen) {
      if (details[entry.attachment]) {
        continue;
      }

      api.current
        .get(`/plugin/${slug}/part/${part.pk}/files/`, { params: { describe: entry.attachment } })
        .then((response) => {
          if (!cancelled) {
            const file = apiData<{ file: FileDetail }>(response, 'file').file;

            setDetails((current) => ({ ...current, [file.attachment]: file }));
          }
        })
        .catch(() => {
          // The row simply shows no details
        });
    }

    return () => {
      cancelled = true;
    };
    // 'details' is left out on purpose: a file is only asked for once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, wanted, slug, part.pk]);

  const chosenDetails = chosen.map((entry) => details[entry.attachment]).filter(Boolean);
  const partsHint = chosenDetails.find((file) => file.summary.parts_hint)?.summary ?? null;
  const minutesHint = chosenDetails.reduce(
    (total, file) => total + (file.summary.minutes_hint ?? 0),
    0
  );
  const cover = chosenDetails.find((file) => file.summary.has_cover) ?? null;

  // Suggest what the files say, until a number is typed
  useEffect(() => {
    if (!perRunEdited && partsHint?.parts_hint) {
      setPerRun(partsHint.parts_hint);
    }
  }, [partsHint, perRunEdited]);

  useEffect(() => {
    if (!minutesEdited && minutesHint > 0) {
      setMinutes(minutesHint);
    }
  }, [minutesHint, minutesEdited]);

  const add = (attachment: number) => {
    setChosen((current) =>
      current.some((entry) => entry.attachment === attachment)
        ? current
        : [...current, { attachment, label: '' }]
    );
    setErrors((current) => ({ ...current, files: '' }));
  };

  const move = (index: number, by: number) => {
    setChosen((current) => {
      const next = current.slice();
      const target = index + by;

      if (target < 0 || target >= next.length) {
        return current;
      }

      [next[index], next[target]] = [next[target], next[index]];

      return next;
    });
  };

  const upload = async (picked: File[]) => {
    if (picked.length === 0) {
      return;
    }

    setUploading(true);
    setError(null);

    try {
      // One after the other, so that they are listed in the order they were picked
      for (const file of picked) {
        const form = new FormData();
        form.append('file', file);

        const response: any = await api.current.post(`/plugin/${slug}/part/${part.pk}/files/`, form, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        const stored = apiData<{ file: FileDetail }>(response, 'file').file;

        setAttached((current) => [
          {
            attachment: stored.attachment,
            filename: stored.filename,
            file_size: stored.file_size ?? file.size,
            comment: '',
            uploaded: new Date().toISOString().slice(0, 10),
            uploaded_by: null,
            kind: stored.summary.kind,
            kind_name: stored.summary.kind_name,
            linked: false
          },
          ...(current ?? [])
        ]);
        setDetails((current) => ({ ...current, [stored.attachment]: stored }));
        add(stored.attachment);
      }
    } catch (err: any) {
      setError(apiError(err, 'Could not attach the file'));
    } finally {
      setUploading(false);
      resetUpload.current?.();
    }
  };

  const save = () => {
    setBusy('save');
    setError(null);
    setErrors({});

    api.current
      .put(`/plugin/${slug}/part/${part.pk}/`, {
        machine,
        files: chosen,
        parts_per_run: asNumber(perRun),
        run_minutes: asNumber(minutes),
        restock_to: asNumber(restockTo),
        destination,
        setup_notes: setupNotes
      })
      .then(() => {
        onSaved();
        onClose();
      })
      .catch((err: any) => {
        const fields = fieldErrors(err);

        setErrors(fields);

        if (Object.keys(fields).every((key) => key === 'detail')) {
          setError(apiError(err, 'Could not save the link'));
        }
      })
      .finally(() => setBusy(null));
  };

  const remove = () => {
    setBusy('remove');
    setError(null);

    api.current
      .delete(`/plugin/${slug}/part/${part.pk}/`)
      .then(() => {
        onSaved();
        onClose();
      })
      .catch((err: any) => setError(apiError(err, 'Could not remove the link')))
      .finally(() => setBusy(null));
  };

  const nameOf = (attachment: number) =>
    details[attachment]?.filename ??
    attached?.find((entry) => entry.attachment === attachment)?.filename ??
    `File ${attachment}`;

  const addable = (attached ?? [])
    .filter((entry) => !chosen.some((item) => item.attachment === entry.attachment))
    .sort((a, b) => Number(b.kind !== '') - Number(a.kind !== '') || b.attachment - a.attachment)
    .map((entry) => ({
      value: String(entry.attachment),
      label: [entry.filename, fmtBytes(entry.file_size), fmtDate(entry.uploaded)]
        .filter(Boolean)
        .join(' · ')
    }));

  const count = asNumber(perRun);
  const anyMissing = chosen.some((entry) => details[entry.attachment]?.missing);
  const missingFiles = (link?.files ?? []).filter((file) => file.missing);
  const chosenMachine = machines?.find((entry) => entry.id === machine) ?? null;

  return (
    <>
      <Modal
        opened={opened && !managing}
        onClose={onClose}
        title={link ? `How ${part.name} is made` : `Link ${part.name} to a machine`}
        centered
        size='lg'
      >
        <Stack gap='md'>
          {link?.machine_missing && (
            <Alert color='red' title='The machine of this part was removed'>
              Choose the machine which makes it now.
            </Alert>
          )}

          {missingFiles.length > 0 && (
            <Alert color='red' title='A linked file is gone'>
              {missingFiles.map((file) => `"${file.filename}"`).join(', ')}{' '}
              {missingFiles.length === 1 ? 'is' : 'are'} no longer attached to the part. Choose or
              upload {missingFiles.length === 1 ? 'it' : 'them'} again.
            </Alert>
          )}

          <Stack gap={4}>
            <Select
              label='Machine'
              placeholder={
                machines === null
                  ? 'Loading'
                  : machines.length > 0
                    ? 'Choose the machine which makes this part'
                    : 'No machine has been added yet'
              }
              data={(machines ?? []).map((entry) => ({
                value: String(entry.id),
                label: entry.name
              }))}
              value={machine !== null ? String(machine) : null}
              onChange={(value) => setMachine(value ? Number(value) : null)}
              disabled={machines === null || machines.length === 0}
              error={errors.machine}
              withAsterisk
              comboboxProps={{ withinPortal: true }}
            />
            <Group justify='space-between' gap='xs'>
              <Text size='xs' c='dimmed' style={{ whiteSpace: 'pre-wrap', flex: 1 }}>
                {chosenMachine?.notes ?? ''}
              </Text>
              {canManageMachines && (
                <Anchor component='button' type='button' size='xs' onClick={() => setManaging(true)}>
                  {machines && machines.length === 0 ? 'Add a machine' : 'Manage machines'}
                </Anchor>
              )}
            </Group>
          </Stack>

          <Stack gap='xs'>
            <Stack gap={0}>
              <Text size='sm' fw={500}>
                Files{' '}
                <Text span c='red'>
                  *
                </Text>
              </Text>
              <Text size='xs' c='dimmed'>
                What is taken to the machine, in the order it is used: an xTool project, G-code
                programs, the CAM project, a fixture drawing. They are kept as attachments of the
                part.
              </Text>
            </Stack>

            {attached === null && <Loader size='sm' />}

            {chosen.map((entry, index) => {
              const file = details[entry.attachment];

              return (
                <Paper withBorder p='xs' key={entry.attachment} data-file-row={entry.attachment}>
                  <Group align='flex-start' wrap='nowrap' gap='sm'>
                    <Text size='sm' c='dimmed' w={16} ta='right' pt={2}>
                      {index + 1}
                    </Text>
                    <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
                      <Text fw={600} size='sm' style={{ wordBreak: 'break-all' }}>
                        {nameOf(entry.attachment)}
                      </Text>
                      {file ? (
                        file.missing ? (
                          <Text size='sm' c='red'>
                            This file is missing from the InvenTree file storage. Upload it again.
                          </Text>
                        ) : (
                          <FileDetails summary={file.summary} />
                        )
                      ) : (
                        <Text size='xs' c='dimmed'>
                          Reading the file
                        </Text>
                      )}
                      {chosen.length > 1 && (
                        <TextInput
                          aria-label={`Label of ${nameOf(entry.attachment)}`}
                          placeholder='Label, e.g. Side A (optional)'
                          size='xs'
                          value={entry.label}
                          maxLength={60}
                          onChange={(event) => {
                            const label = event.currentTarget.value;

                            setChosen((current) =>
                              current.map((item) =>
                                item.attachment === entry.attachment ? { ...item, label } : item
                              )
                            );
                          }}
                        />
                      )}
                    </Stack>
                    <Group gap={2} wrap='nowrap'>
                      {chosen.length > 1 && (
                        <>
                          <Tooltip label='Earlier'>
                            <ActionIcon
                              variant='subtle'
                              aria-label={`Move ${nameOf(entry.attachment)} earlier`}
                              disabled={index === 0}
                              onClick={() => move(index, -1)}
                            >
                              <IconArrowUp size={16} />
                            </ActionIcon>
                          </Tooltip>
                          <Tooltip label='Later'>
                            <ActionIcon
                              variant='subtle'
                              aria-label={`Move ${nameOf(entry.attachment)} later`}
                              disabled={index === chosen.length - 1}
                              onClick={() => move(index, 1)}
                            >
                              <IconArrowDown size={16} />
                            </ActionIcon>
                          </Tooltip>
                        </>
                      )}
                      <Tooltip label='Take off the list (the file stays attached to the part)'>
                        <ActionIcon
                          variant='subtle'
                          color='red'
                          aria-label={`Take ${nameOf(entry.attachment)} off the list`}
                          onClick={() =>
                            setChosen((current) =>
                              current.filter((item) => item.attachment !== entry.attachment)
                            )
                          }
                        >
                          <IconX size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                </Paper>
              );
            })}

            <Group align='flex-end' wrap='nowrap'>
              <Select
                aria-label='Add a file of the part'
                placeholder={
                  addable.length > 0
                    ? 'Add a file which is attached to the part'
                    : chosen.length > 0
                      ? 'No other file is attached to the part'
                      : 'No file is attached to this part yet'
                }
                data={addable}
                value={null}
                onChange={(value) => value && add(Number(value))}
                disabled={attached === null || addable.length === 0}
                comboboxProps={{ withinPortal: true }}
                style={{ flex: 1, minWidth: 0 }}
              />
              <FileButton resetRef={resetUpload} onChange={upload} multiple>
                {(props) => (
                  <Button
                    {...props}
                    variant='default'
                    leftSection={<IconUpload size={16} />}
                    loading={uploading}
                  >
                    Upload
                  </Button>
                )}
              </FileButton>
            </Group>
            {errors.files && (
              <Text size='xs' c='red'>
                {errors.files}
              </Text>
            )}
          </Stack>

          {cover && (
            <Group align='center' wrap='nowrap' gap='md'>
              <Preview
                context={context}
                url={`/plugin/${slug}/part/${part.pk}/preview/?attachment=${cover.attachment}`}
                size={96}
              />
              <Text size='sm' c='dimmed'>
                Preview stored in {cover.filename}
              </Text>
            </Group>
          )}

          <Group grow align='flex-start'>
            <NumberInput
              label='Good parts from one run'
              description={partsHint?.parts_hint_text || 'How many parts one run of the files gives'}
              value={perRun}
              onChange={(value) => {
                setPerRun(value);
                setPerRunEdited(true);
              }}
              min={1}
              allowDecimal={false}
              error={errors.parts_per_run}
              withAsterisk
            />
            <NumberInput
              label='Machine time of one run'
              description={
                minutesHint > 0
                  ? `Minutes. The files say ${fmtMinutes(minutesHint)}`
                  : 'Minutes, with loading and unloading. Optional'
              }
              placeholder='Optional'
              value={minutes}
              onChange={(value) => {
                setMinutes(value);
                setMinutesEdited(true);
              }}
              min={0}
              error={errors.run_minutes}
            />
          </Group>

          <Group grow align='flex-start'>
            <NumberInput
              label='Make up to'
              description={
                part.minimum_stock > 0
                  ? `When stock is below the minimum of ${fmtQty(part.minimum_stock)}. Empty: up to the minimum`
                  : 'Stock level to suggest making up to. Needs a minimum stock on the part'
              }
              placeholder='Optional'
              value={restockTo}
              onChange={setRestockTo}
              min={0}
              error={errors.restock_to}
            />
            <LocationSelect
              context={context}
              label='Finished parts go to'
              description='Empty: the default location of the part'
              value={destination}
              valueLabel={link?.destination_name}
              onChange={setDestination}
              error={errors.destination}
            />
          </Group>

          <Textarea
            label='Setup notes'
            description='Shown on every job: how to hold and line the material up, which tools, anything to watch'
            placeholder='Optional'
            value={setupNotes}
            onChange={(event) => setSetupNotes(event.currentTarget.value)}
            autosize
            minRows={2}
            maxRows={6}
            maxLength={2000}
            error={errors.setup_notes}
          />

          {!part.assembly && (
            <Text size='sm' c='dimmed'>
              Linking marks the part as an assembly. InvenTree needs that to raise build orders
              for it, and to give it a bill of materials for the stock it is made from.
            </Text>
          )}

          {error && <Alert color='red'>{error}</Alert>}

          {confirmRemove ? (
            <Alert color='red' title='Remove the link?'>
              <Stack gap='sm'>
                <Text size='sm'>
                  The files stay attached to the part, and jobs which exist stay as they are.
                </Text>
                <Group>
                  <Button color='red' size='xs' loading={busy === 'remove'} onClick={remove}>
                    Remove the link
                  </Button>
                  <Button variant='default' size='xs' onClick={() => setConfirmRemove(false)}>
                    Keep it
                  </Button>
                </Group>
              </Stack>
            </Alert>
          ) : (
            <Group justify='space-between'>
              {link ? (
                <Button
                  variant='subtle'
                  color='red'
                  leftSection={<IconTrash size={16} />}
                  onClick={() => setConfirmRemove(true)}
                >
                  Remove link
                </Button>
              ) : (
                <span />
              )}
              <Group>
                <Button variant='default' onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  onClick={save}
                  loading={busy === 'save'}
                  disabled={
                    machine === null || chosen.length === 0 || count === null || count < 1 || anyMissing
                  }
                >
                  {link ? 'Save' : 'Link the part'}
                </Button>
              </Group>
            </Group>
          )}
        </Stack>
      </Modal>

      <MachinesModal
        context={context}
        slug={slug}
        opened={opened && managing}
        canEdit={canManageMachines}
        onClose={() => setManaging(false)}
        onChanged={() => setMachinesKey((key) => key + 1)}
      />
    </>
  );
}
