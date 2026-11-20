import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  Tooltip
} from '@mantine/core';
import { IconCheck, IconDownload, IconPhotoOff, IconTools, IconX } from '@tabler/icons-react';
import { type ReactNode, useEffect, useRef, useState } from 'react';

import {
  JOB_STATE,
  KIND_COLOR,
  apiError,
  fmtDateTime,
  fmtMaterial,
  fmtMinutes,
  fmtQty,
  plural,
  runsFor
} from './format';
import type { FileSummary, Job, Link, MachineKind, PartLabel, Permissions } from './types';

/** The rows of an InvenTree list response, paginated or not */
export function listRows(response: any): any[] {
  const data = response?.data;
  const rows = Array.isArray(data) ? data : data?.results;

  return Array.isArray(rows) ? rows : [];
}

export function partUrl(pk: number): string {
  return `/part/${pk}/`;
}

export function buildUrl(pk: number): string {
  return `/manufacturing/build-order/${pk}/`;
}

/** A link which navigates inside the InvenTree single page app */
export function AppLink({
  context,
  to,
  children,
  title
}: Readonly<{
  context: InvenTreePluginContext;
  to: string;
  children: ReactNode;
  title?: string;
}>) {
  return (
    <Anchor
      href={`/web${to}`}
      title={title}
      size='sm'
      onClick={(event) => {
        // Let the browser handle ctrl / cmd / middle click (open in a new tab)
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
          return;
        }

        event.preventDefault();
        context.navigate(to);
      }}
    >
      {children}
    </Anchor>
  );
}

/** A number with a label, for the row of figures at the top of a panel */
export function Figure({
  label,
  value,
  hint,
  color
}: Readonly<{ label: string; value: string; hint?: ReactNode; color?: string }>) {
  return (
    <Paper withBorder p='sm'>
      <Text size='xs' c='dimmed' tt='uppercase' fw={600}>
        {label}
      </Text>
      <Text fz={24} fw={700} lh={1.25} c={color} style={{ fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </Text>
      {hint && (
        <Text size='xs' c='dimmed'>
          {hint}
        </Text>
      )}
    </Paper>
  );
}

/** The file name the server gave a download */
function downloadName(header: string | undefined, fallback: string): string {
  if (!header) {
    return fallback;
  }

  const encoded = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);

  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      // Fall through to the plain name
    }
  }

  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(header);

  return plain ? plain[1] : fallback;
}

/**
 * Fetch a file through the plugin API and hand it to the browser as a download.
 *
 * The request goes through InvenTree's own API client, so that it carries the
 * login of the user however they are logged in.
 */
export function downloadFile(
  context: InvenTreePluginContext,
  url: string,
  fallbackName: string
): Promise<void> {
  return context.api.get(url, { responseType: 'blob' }).then((response: any) => {
    const blob: Blob = response.data;

    // With URL integration off, InvenTree answers with the web interface
    if (!(blob instanceof Blob) || blob.type.startsWith('text/html')) {
      throw Object.assign(new Error('not a file'), { noApi: true });
    }

    const name = downloadName(response.headers?.['content-disposition'], fallbackName);
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement('a');

    anchor.href = href;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();

    window.setTimeout(() => URL.revokeObjectURL(href), 60000);
  });
}

/** Button: download the files of a part or a job, to take them to the machine */
export function DownloadButton({
  context,
  url,
  filename,
  label,
  variant,
  size
}: Readonly<{
  context: InvenTreePluginContext;
  url: string;
  filename: string;
  label?: string;
  variant?: string;
  size?: string;
}>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = () => {
    setBusy(true);
    setError(null);

    downloadFile(context, url, filename)
      .catch((err: any) =>
        setError(
          err?.response?.status === 404
            ? 'The file is no longer attached to the part.'
            : apiError(err, 'Could not download the file')
        )
      )
      .finally(() => setBusy(false));
  };

  return (
    <Tooltip label={error} opened={error !== null} color='red' withArrow>
      <Button
        size={size ?? 'xs'}
        variant={variant ?? 'default'}
        leftSection={<IconDownload size={14} />}
        loading={busy}
        onClick={start}
        onBlur={() => setError(null)}
      >
        {label ?? 'Download'}
      </Button>
    </Tooltip>
  );
}

/** The picture stored in a file (xTool projects have one) */
export function Preview({
  context,
  url,
  size
}: Readonly<{ context: InvenTreePluginContext; url: string | null; size?: number }>) {
  const api = useRef(context.api);
  api.current = context.api;

  const [source, setSource] = useState<string | null>(null);
  const box = size ?? 96;

  useEffect(() => {
    if (!url) {
      setSource(null);
      return;
    }

    let cancelled = false;
    let created: string | null = null;

    api.current
      .get(url, { responseType: 'blob' })
      .then((response: any) => {
        const blob: Blob = response.data;

        if (cancelled || !(blob instanceof Blob) || !blob.type.startsWith('image/')) {
          return;
        }

        created = URL.createObjectURL(blob);
        setSource(created);
      })
      .catch(() => {
        if (!cancelled) {
          setSource(null);
        }
      });

    return () => {
      cancelled = true;

      if (created) {
        URL.revokeObjectURL(created);
      }
    };
  }, [url]);

  return (
    <Paper
      withBorder
      w={box}
      h={box}
      p={4}
      style={{ flexShrink: 0, background: 'white', overflow: 'hidden' }}
    >
      {source ? (
        <img
          src={source}
          alt='Preview of the file'
          style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
        />
      ) : (
        <Center h='100%'>
          <IconPhotoOff size={22} color='var(--mantine-color-gray-5)' aria-label='No preview' />
        </Center>
      )}
    </Paper>
  );
}

/** The machine a part is made on, as a badge */
export function MachineBadge({
  name,
  kind
}: Readonly<{ name: string | null | undefined; kind: MachineKind | null | undefined }>) {
  if (!name) {
    return (
      <Badge color='red' variant='light' radius='sm' tt='none'>
        Machine removed
      </Badge>
    );
  }

  return (
    <Badge color={KIND_COLOR[kind ?? 'other'] ?? 'gray'} variant='light' radius='sm' tt='none'>
      {name}
    </Badge>
  );
}

/** What a file says about itself: a line of facts and a badge for each thing it does */
export function FileDetails({ summary }: Readonly<{ summary: FileSummary }>) {
  if (!summary.recognised) {
    return (
      <Text size='sm' c='dimmed'>
        {summary.notes[0] ??
          (summary.kind
            ? `The content of this ${summary.kind_name} could not be read. It is stored and handed back as it is.`
            : 'Stored and handed back as it is.')}
      </Text>
    );
  }

  return (
    <Stack gap={4}>
      {summary.facts.length > 0 && <Text size='sm'>{summary.facts.join(' · ')}</Text>}
      {summary.operations.length > 0 && (
        <Group gap={6} wrap='wrap'>
          {summary.operations.map((operation, index) => (
            <Badge
              key={`${operation.label}-${index}`}
              variant='light'
              color={operation.tone === 'cut' ? 'red' : 'blue'}
              radius='sm'
              tt='none'
              fw={500}
            >
              {operation.detail ? `${operation.label} · ${operation.detail}` : operation.label}
            </Badge>
          ))}
        </Group>
      )}
      {summary.notes.map((note) => (
        <Text size='xs' c='dimmed' key={note}>
          {note}
        </Text>
      ))}
    </Stack>
  );
}

/** Search box for a stock location */
export function LocationSelect({
  context,
  value,
  valueLabel,
  onChange,
  label,
  description,
  placeholder,
  error
}: Readonly<{
  context: InvenTreePluginContext;
  value: number | null;
  valueLabel?: string | null;
  onChange: (value: number | null) => void;
  label: string;
  description?: string;
  placeholder?: string;
  error?: string;
}>) {
  const api = useRef(context.api);
  api.current = context.api;

  const [search, setSearch] = useState('');
  const [options, setOptions] = useState<{ value: string; label: string }[]>(
    value && valueLabel ? [{ value: String(value), label: valueLabel }] : []
  );

  useEffect(() => {
    let cancelled = false;

    const timer = window.setTimeout(() => {
      api.current
        .get('/api/stock/location/', {
          params: { search: search || undefined, limit: 30, ordering: 'pathstring' }
        })
        .then((response) => {
          if (cancelled) {
            return;
          }

          const found = listRows(response).map((row) => ({
            value: String(row.pk),
            label: String(row.pathstring ?? row.name)
          }));

          setOptions((current) => {
            // Keep the chosen location in the list, so that its name still shows
            const chosen = current.find((option) => option.value === String(value));

            return chosen && !found.some((option) => option.value === chosen.value)
              ? [chosen, ...found]
              : found;
          });
        })
        .catch(() => {
          // The list simply stays as it is
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [search, value]);

  return (
    <Select
      label={label}
      description={description}
      placeholder={placeholder ?? 'Search for a location'}
      data={options}
      value={value ? String(value) : null}
      onChange={(next) => onChange(next ? Number(next) : null)}
      searchable
      clearable
      onSearchChange={setSearch}
      filter={({ options: all }) => all}
      nothingFoundMessage='No location found'
      error={error}
      comboboxProps={{ withinPortal: true }}
    />
  );
}

function asNumber(value: number | string): number {
  return typeof value === 'number' ? value : Number(value) || 0;
}

/** Dialog: how many parts to make */
export function MakeModal({
  context,
  slug,
  part,
  link,
  suggested,
  opened,
  onClose,
  onDone
}: Readonly<{
  context: InvenTreePluginContext;
  slug: string;
  part: PartLabel;
  link: Link;
  suggested?: number;
  opened: boolean;
  onClose: () => void;
  onDone: () => void;
}>) {
  const perRun = link.parts_per_run;
  const [quantity, setQuantity] = useState<number | string>(perRun);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only when the dialog opens: a refresh behind it must not reset the number
  const start = useRef(perRun);
  start.current = suggested && suggested > 0 ? suggested : perRun;

  useEffect(() => {
    if (opened) {
      setQuantity(start.current);
      setNotes('');
      setError(null);
    }
  }, [opened]);

  const runs = runsFor(asNumber(quantity), perRun);
  const made = runs * perRun;
  const time = link.run_minutes ? fmtMinutes(link.run_minutes * runs) : '';

  const submit = () => {
    setBusy(true);
    setError(null);

    context.api
      .post(`/plugin/${slug}/part/${part.pk}/make/`, { runs, notes })
      .then(() => {
        onDone();
        onClose();
      })
      .catch((err: any) => setError(apiError(err, 'Could not raise the job')))
      .finally(() => setBusy(false));
  };

  return (
    <Modal opened={opened} onClose={onClose} title={`Make ${part.name}`} centered>
      <Stack gap='md'>
        <NumberInput
          label='Parts needed'
          description={`${fmtQty(perRun)} from one run. Rounded up to whole runs.`}
          value={quantity}
          onChange={setQuantity}
          min={1}
          allowDecimal={false}
          data-autofocus
        />
        <Paper withBorder p='sm'>
          <Text fw={600}>
            {plural(runs, 'run')}, {plural(made, 'part')}
          </Text>
          <Text size='sm' c='dimmed'>
            {[`on ${link.machine_name ?? 'a machine which was removed'}`, time ? `about ${time} of machine time` : '']
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </Paper>
        <Textarea
          label='Note for whoever makes it'
          placeholder='Optional'
          value={notes}
          onChange={(event) => setNotes(event.currentTarget.value)}
          autosize
          minRows={1}
          maxLength={250}
        />
        <Text size='sm' c='dimmed'>
          A build order is raised for the {plural(made, 'part')}, so they count as on their way.
          Nothing is sent to the machine: the files are taken to it and run by hand.
        </Text>
        {error && <Alert color='red'>{error}</Alert>}
        <Group justify='flex-end'>
          <Button variant='default' onClick={onClose}>
            Cancel
          </Button>
          <Button
            leftSection={<IconTools size={16} />}
            onClick={submit}
            loading={busy}
            disabled={runs < 1}
          >
            Raise a job for {plural(runs, 'run')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

type JobDialog = 'book' | 'close' | 'cancel' | null;

/** One job: its state, what was booked and what can be done next */
export function JobCard({
  context,
  slug,
  job,
  permissions,
  setupNotes,
  showPart,
  onChanged
}: Readonly<{
  context: InvenTreePluginContext;
  slug: string;
  job: Job;
  permissions: Permissions;
  setupNotes?: string;
  showPart?: boolean;
  onChanged: () => void;
}>) {
  const summary = job.summary;
  const state = JOB_STATE[summary.state] ?? JOB_STATE.open;
  const active = summary.state === 'open' || summary.state === 'partial';
  const perRun = job.parts_per_run || 1;

  const [dialog, setDialog] = useState<JobDialog>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [runs, setRuns] = useState<number | string>(1);
  const [good, setGood] = useState<number | string>(0);
  const [goodEdited, setGoodEdited] = useState(false);
  const [used, setUsed] = useState<Record<number, number | string>>({});
  const [usedEdited, setUsedEdited] = useState<Record<number, boolean>>({});
  const [location, setLocation] = useState<number | null>(job.destination);
  const [notes, setNotes] = useState('');
  const [finish, setFinish] = useState(false);

  const act = (action: string, body: Record<string, unknown> = {}) => {
    setBusy(action);
    setError(null);

    return context.api
      .post(`/plugin/${slug}/job/${job.build}/${action}/`, body)
      .then(() => {
        setDialog(null);
        onChanged();
      })
      .catch((err: any) => setError(apiError(err, 'That did not work')))
      .finally(() => setBusy(null));
  };

  const materialFor = (count: number): Record<number, number> =>
    Object.fromEntries(
      job.material.map((line) => [line.line, Math.round(line.per_run * count * 10000) / 10000])
    );

  const open = (which: JobDialog) => {
    setError(null);

    if (which === 'book') {
      const count = Math.max(1, summary.runs_left);

      setRuns(count);
      setGood(count * perRun);
      setGoodEdited(false);
      setUsed(materialFor(count));
      setUsedEdited({});
      setLocation(job.destination);
      setNotes('');
      setFinish(false);
    }

    setDialog(which);
  };

  // The good parts and the material follow the runs until they are typed over
  const changeRuns = (value: number | string) => {
    const count = asNumber(value);

    setRuns(value);

    if (!goodEdited) {
      setGood(count * perRun);
    }

    const fresh = materialFor(count);

    setUsed((current) =>
      Object.fromEntries(
        job.material.map((line) => [
          line.line,
          usedEdited[line.line] ? current[line.line] : fresh[line.line]
        ])
      )
    );
  };

  const runCount = asNumber(runs);
  const goodCount = asNumber(good);
  const most = runCount * perRun;
  const shortAfter = Math.max(0, summary.remaining - goodCount);
  const tooMany = goodCount > most;

  const shortMaterial = job.material.filter((line) => asNumber(used[line.line] ?? 0) > line.in_stock);

  const submitBooking = () =>
    act('book', {
      good: goodCount,
      runs: runCount,
      location,
      notes,
      finish: finish && shortAfter > 0,
      material: job.material.map((line) => ({
        line: line.line,
        quantity: asNumber(used[line.line] ?? 0)
      }))
    });

  const facts = [
    `${plural(summary.runs_planned, 'run')} × ${fmtQty(perRun)}`,
    summary.runs_done > 0 ? `${plural(summary.runs_done, 'run')} done` : '',
    summary.rejected > 0 ? `${plural(summary.rejected, 'reject')}` : '',
    active && job.run_minutes && summary.runs_left > 0
      ? `about ${fmtMinutes(job.run_minutes * summary.runs_left)} to go`
      : ''
  ].filter(Boolean);

  const fileNames = job.files
    .map((file) => (file.label ? `${file.label}: ${file.filename}` : file.filename))
    .join(', ');

  return (
    <Paper withBorder p='sm'>
      <Stack gap='xs'>
        <Group justify='space-between' align='flex-start' wrap='wrap' gap='xs'>
          <Stack gap={2}>
            <Group gap='xs' wrap='wrap'>
              <AppLink context={context} to={buildUrl(job.build)} title='Open the build order'>
                <Text fw={600} span>
                  {job.reference}
                </Text>
              </AppLink>
              <Tooltip label={state.hint} multiline w={260}>
                <Badge color={state.color} variant='light'>
                  {state.label}
                </Badge>
              </Tooltip>
              {job.machine && <MachineBadge name={job.machine.name} kind={job.machine.kind} />}
              {showPart && (
                <AppLink context={context} to={partUrl(job.part)}>
                  {job.part_ipn ? `${job.part_ipn} · ${job.part_name}` : job.part_name}
                </AppLink>
              )}
            </Group>
            <Text size='sm'>
              {fmtQty(job.completed)} of {fmtQty(job.quantity)} in stock · {facts.join(' · ')}
            </Text>
            <Text size='xs' c='dimmed' style={{ wordBreak: 'break-word' }}>
              {fileNames}
              {job.issued_by ? ` · raised by ${job.issued_by}` : ''}
              {job.destination_name ? ` · to ${job.destination_name}` : ''}
            </Text>
          </Stack>
          {active && (
            <Group gap='xs' wrap='wrap'>
              <DownloadButton
                context={context}
                url={`/plugin/${slug}/job/${job.build}/download/`}
                filename={job.files.length === 1 ? (job.files[0].filename ?? 'file') : `${job.reference}-files.zip`}
                label={job.files.length === 1 ? 'Download the file' : `Download the ${job.files.length} files`}
              />
              {permissions.manage && summary.can_book && (
                <Button
                  size='xs'
                  color='orange'
                  leftSection={<IconCheck size={14} />}
                  onClick={() => open('book')}
                >
                  Book parts
                </Button>
              )}
              {permissions.manage && summary.can_close && (
                <Button size='xs' variant='default' onClick={() => open('close')}>
                  {summary.remaining > 0 ? 'Close short' : 'Close'}
                </Button>
              )}
              {permissions.manage && summary.can_cancel && (
                <Button
                  size='xs'
                  variant='subtle'
                  color='red'
                  leftSection={<IconX size={14} />}
                  onClick={() => open('cancel')}
                >
                  Cancel
                </Button>
              )}
            </Group>
          )}
        </Group>

        {active && (job.notes || setupNotes) && (
          <Stack gap={2}>
            {setupNotes && (
              <Text size='sm' style={{ whiteSpace: 'pre-wrap' }}>
                <Text span fw={600} size='sm'>
                  Setup:{' '}
                </Text>
                {setupNotes}
              </Text>
            )}
            {job.notes && (
              <Text size='sm' style={{ whiteSpace: 'pre-wrap' }}>
                <Text span fw={600} size='sm'>
                  Note:{' '}
                </Text>
                {job.notes}
              </Text>
            )}
          </Stack>
        )}

        {job.bookings.length > 0 && (
          <Stack gap={0}>
            {job.bookings.map((booking, index) => (
              <Text size='xs' c='dimmed' key={`${booking.at}-${index}`}>
                {fmtDateTime(booking.at)}: {plural(booking.good, 'good part')} from{' '}
                {plural(booking.runs, 'run')}
                {booking.material.length > 0
                  ? `, used ${booking.material
                      .map((entry) => `${fmtMaterial(entry.quantity, entry.units)} ${entry.name}`)
                      .join(', ')}`
                  : ''}
                {booking.by ? ` · ${booking.by}` : ''}
                {booking.notes ? ` · ${booking.notes}` : ''}
              </Text>
            ))}
          </Stack>
        )}

        {error && dialog === null && <Alert color='red'>{error}</Alert>}
      </Stack>

      <Modal
        opened={dialog === 'book'}
        onClose={() => setDialog(null)}
        title={`Book the parts of ${job.reference}`}
        centered
      >
        <Stack gap='md'>
          <Text size='sm'>
            {summary.remaining > 0
              ? `${plural(summary.remaining, 'part')} still to come for this job.`
              : 'This job has its quantity. Anything more is booked on top.'}{' '}
            Enter what was made. The good parts are booked into stock against the build order.
          </Text>
          <Group grow align='flex-start'>
            <NumberInput
              label='Runs done'
              description={`${fmtQty(perRun)} parts a run`}
              value={runs}
              onChange={changeRuns}
              min={1}
              allowDecimal={false}
              data-autofocus
            />
            <NumberInput
              label='Good parts'
              description={`Up to ${fmtQty(most)}`}
              value={good}
              onChange={(value) => {
                setGood(value);
                setGoodEdited(true);
              }}
              min={0}
              allowDecimal={false}
              error={tooMany ? 'More than the runs can give' : undefined}
            />
          </Group>

          {job.material.length > 0 && (
            <Stack gap='xs'>
              {job.material.map((line) => (
                <NumberInput
                  key={line.line}
                  label={`${line.name} used`}
                  description={`${fmtMaterial(line.per_run, line.units)} a run by the bill of materials · ${fmtMaterial(line.in_stock, line.units)} in stock`}
                  value={used[line.line] ?? 0}
                  onChange={(value) => {
                    setUsed((current) => ({ ...current, [line.line]: value }));
                    setUsedEdited((current) => ({ ...current, [line.line]: true }));
                  }}
                  min={0}
                  decimalScale={4}
                  error={
                    shortMaterial.includes(line) ? 'More than there is in stock' : undefined
                  }
                />
              ))}
              <Text size='xs' c='dimmed'>
                Taken from stock against the build order. Enter 0 to take nothing.
              </Text>
            </Stack>
          )}

          <LocationSelect
            context={context}
            label='Into location'
            value={location}
            valueLabel={job.destination_name}
            onChange={setLocation}
            placeholder='Default location of the part'
          />
          <Textarea
            label='Note'
            placeholder='Optional'
            value={notes}
            onChange={(event) => setNotes(event.currentTarget.value)}
            autosize
            minRows={1}
            maxLength={250}
          />

          {shortAfter > 0 ? (
            <Stack gap={6}>
              <Switch
                label='Close the job with this'
                checked={finish}
                onChange={(event) => setFinish(event.currentTarget.checked)}
              />
              <Text size='sm' c='dimmed'>
                {finish
                  ? goodCount > 0 || job.completed > 0
                    ? `The build order is completed ${plural(shortAfter, 'part')} short.`
                    : 'Nothing good came out, so the build order is cancelled.'
                  : `That leaves the job ${plural(shortAfter, 'part')} short. It stays open for the rest.`}
              </Text>
            </Stack>
          ) : (
            <Text size='sm' c='dimmed'>
              That completes the build order.
            </Text>
          )}

          {error && <Alert color='red'>{error}</Alert>}
          <Group justify='flex-end'>
            <Button variant='default' onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button
              color='orange'
              loading={busy === 'book'}
              disabled={runCount < 1 || tooMany || shortMaterial.length > 0}
              onClick={submitBooking}
            >
              Book {plural(goodCount, 'part')} into stock
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={dialog === 'close'}
        onClose={() => setDialog(null)}
        title={`Close ${job.reference}`}
        centered
      >
        <Stack gap='md'>
          <Text size='sm'>
            The build order is completed with the {plural(job.completed, 'part')} which are in
            stock
            {summary.remaining > 0
              ? `, ${plural(summary.remaining, 'part')} fewer than it asked for.`
              : '.'}
          </Text>
          {error && <Alert color='red'>{error}</Alert>}
          <Group justify='flex-end'>
            <Button variant='default' onClick={() => setDialog(null)}>
              Keep it open
            </Button>
            <Button loading={busy === 'close'} onClick={() => act('close')}>
              Close the job
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={dialog === 'cancel'}
        onClose={() => setDialog(null)}
        title={`Cancel ${job.reference}`}
        centered
      >
        <Stack gap='md'>
          <Text size='sm'>
            Nothing of this job is in stock, so its build order is cancelled.
            {summary.runs_done > 0 ? ' Material which was booked as used stays used.' : ''}
          </Text>
          {error && <Alert color='red'>{error}</Alert>}
          <Group justify='flex-end'>
            <Button variant='default' onClick={() => setDialog(null)}>
              Keep the job
            </Button>
            <Button color='red' loading={busy === 'cancel'} onClick={() => act('cancel')}>
              Cancel the job
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
