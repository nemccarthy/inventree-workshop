import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip
} from '@mantine/core';
import { IconLink, IconPencil, IconRefresh, IconSettings, IconTools } from '@tabler/icons-react';
import { type CSSProperties, useCallback, useEffect, useRef, useState } from 'react';

import { LinkModal } from './LinkModal';
import { MachinesModal } from './MachinesModal';
import { JOB_STATE, apiData, apiError, fmtDate, fmtMinutes, fmtQty, plural } from './format';
import type { OverviewData, OverviewPart, PartLabel } from './types';
import {
  AppLink,
  DownloadButton,
  Figure,
  JobCard,
  MachineBadge,
  MakeModal,
  buildUrl,
  listRows,
  partUrl
} from './ui';

const numCell: CSSProperties = {
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap'
};

/** Dialog: find a part to link */
function PartPicker({
  context,
  opened,
  onClose,
  onPicked
}: Readonly<{
  context: InvenTreePluginContext;
  opened: boolean;
  onClose: () => void;
  onPicked: (part: PartLabel) => void;
}>) {
  const api = useRef(context.api);
  api.current = context.api;

  const [search, setSearch] = useState('');
  const [rows, setRows] = useState<any[]>([]);
  const [value, setValue] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) {
      return;
    }

    let cancelled = false;

    const timer = window.setTimeout(() => {
      api.current
        .get('/api/part/', {
          params: { search: search || undefined, limit: 30, active: true, virtual: false }
        })
        .then((response) => {
          if (!cancelled) {
            setRows(listRows(response));
          }
        })
        .catch(() => {
          // The list simply stays as it is
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [opened, search]);

  useEffect(() => {
    if (opened) {
      setValue(null);
      setSearch('');
    }
  }, [opened]);

  const pick = () => {
    const row = rows.find((entry) => String(entry.pk) === value);

    if (!row) {
      return;
    }

    onPicked({
      pk: row.pk,
      name: row.name,
      ipn: row.IPN ?? '',
      description: row.description ?? '',
      units: row.units ?? '',
      active: row.active,
      assembly: row.assembly,
      trackable: row.trackable,
      minimum_stock: Number(row.minimum_stock ?? 0),
      default_location: row.default_location ?? null
    });
  };

  return (
    <Modal opened={opened} onClose={onClose} title='Link a part' centered>
      <Stack gap='md'>
        <Select
          label='Part'
          placeholder='Search by name or IPN'
          data={rows.map((row) => ({
            value: String(row.pk),
            label: row.IPN ? `${row.IPN} · ${row.full_name ?? row.name}` : (row.full_name ?? row.name)
          }))}
          value={value}
          onChange={setValue}
          searchable
          onSearchChange={setSearch}
          filter={({ options }) => options}
          nothingFoundMessage='No part found'
          comboboxProps={{ withinPortal: true }}
          data-autofocus
        />
        <Group justify='flex-end'>
          <Button variant='default' onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={value === null} onClick={pick}>
            Choose its machine and files
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** What the overview says about making more of a part now */
function suggestionCell(row: OverviewPart) {
  const { suggestion, numbers } = row;

  if (row.link.machine_missing) {
    return (
      <Tooltip label='The machine of this part was removed. Edit the link.'>
        <Badge color='red' variant='light'>
          No machine
        </Badge>
      </Tooltip>
    );
  }

  if (row.link.file_missing) {
    return (
      <Tooltip label='A file is no longer attached to the part. Edit the link.'>
        <Badge color='red' variant='light'>
          File missing
        </Badge>
      </Tooltip>
    );
  }

  if (suggestion.runs > 0) {
    return (
      <Tooltip
        label={
          suggestion.reason === 'build_demand'
            ? `Build orders need ${fmtQty(numbers.demand)}: ${fmtQty(-suggestion.projected + suggestion.floor)} short`
            : `Below the minimum of ${fmtQty(numbers.minimum)}`
        }
      >
        <Badge color='orange' variant='light'>
          Make {plural(suggestion.runs, 'run')}
        </Badge>
      </Tooltip>
    );
  }

  if (row.open_jobs > 0) {
    return (
      <Text size='sm' c='dimmed'>
        {plural(row.open_jobs, 'job')} open
      </Text>
    );
  }

  return (
    <Text size='sm' c='dimmed'>
      {numbers.minimum > 0 ? 'Enough' : 'No minimum set'}
    </Text>
  );
}

/** The Workshop page */
export function WorkshopPage({ context }: Readonly<{ context: InvenTreePluginContext }>) {
  const api = useRef(context.api);
  api.current = context.api;

  const slug = 'workshop';

  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Which machine is shown: 'all', or the id of one
  const [shown, setShown] = useState('all');

  const [picking, setPicking] = useState(false);
  const [managing, setManaging] = useState(false);
  const [linkPart, setLinkPart] = useState<PartLabel | null>(null);
  const [linkRow, setLinkRow] = useState<OverviewPart | null>(null);
  const [makeRow, setMakeRow] = useState<OverviewPart | null>(null);

  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    api.current
      .get(`/plugin/${slug}/overview/`)
      .then((response) => {
        if (!cancelled) {
          setData(apiData<OverviewData>(response, 'parts'));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(apiError(err, 'Could not load the workshop jobs'));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  if (!data) {
    return error ? (
      <Alert color='red' title='Could not load the workshop jobs' m='md'>
        {error}
      </Alert>
    ) : (
      <Center h={300}>
        <Loader />
      </Center>
    );
  }

  const { permissions } = data;

  // A machine which was removed since it was chosen shows everything again
  const machineId = data.machines.some((machine) => String(machine.id) === shown) ? Number(shown) : null;

  const jobs = data.jobs.filter((job) => machineId === null || job.machine?.id === machineId);
  const parts = data.parts.filter((row) => machineId === null || row.link.machine === machineId);
  const history = data.history.filter((job) => machineId === null || job.machine?.id === machineId);

  const toMake = jobs.filter((job) => job.summary.state === 'open').length;
  const partMade = jobs.filter((job) => job.summary.state === 'partial').length;
  const due = parts.filter(
    (row) => row.suggestion.runs > 0 && !row.link.file_missing && !row.link.machine_missing
  );
  const minutes = jobs.reduce(
    (total, job) => total + (job.run_minutes ?? 0) * job.summary.runs_left,
    0
  );
  const untimed = jobs.filter((job) => !job.run_minutes && job.summary.runs_left > 0).length;
  const runsLeft = jobs.reduce((total, job) => total + job.summary.runs_left, 0);

  const notesOf = (part: number) =>
    data.parts.find((row) => row.part.pk === part)?.link.setup_notes;

  return (
    <Stack gap='md' p='md'>
      <Group justify='space-between' wrap='wrap'>
        <Title order={3}>Workshop</Title>
        <Group gap='xs'>
          <Button
            variant='default'
            leftSection={<IconSettings size={16} />}
            onClick={() => setManaging(true)}
          >
            Machines
          </Button>
          {permissions.link && (
            <Button
              variant='default'
              leftSection={<IconLink size={16} />}
              onClick={() => setPicking(true)}
            >
              Link a part
            </Button>
          )}
          <Button
            variant='default'
            leftSection={<IconRefresh size={16} />}
            loading={loading}
            onClick={reload}
          >
            Refresh
          </Button>
        </Group>
      </Group>

      {error && <Alert color='red'>{error}</Alert>}

      {data.machines.length === 0 && (
        <Alert color='blue' title='Start by adding your machines'>
          <Stack gap='sm' align='flex-start'>
            <Text size='sm'>
              Add the laser, the CNC mill and whatever else makes parts in-house. Then link each
              part to its machine and its files.
            </Text>
            {permissions.link && (
              <Button size='xs' onClick={() => setManaging(true)}>
                Add a machine
              </Button>
            )}
          </Stack>
        </Alert>
      )}

      {data.machines.length > 1 && (
        <SegmentedControl
          aria-label='Machine'
          value={machineId === null ? 'all' : String(machineId)}
          onChange={setShown}
          data={[
            { value: 'all', label: 'All machines' },
            ...data.machines.map((machine) => ({ value: String(machine.id), label: machine.name }))
          ]}
          style={{ alignSelf: 'flex-start' }}
        />
      )}

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Figure
          label='To make'
          value={fmtQty(toMake)}
          color={toMake > 0 ? 'violet' : undefined}
          hint='Jobs with nothing booked yet'
        />
        <Figure
          label='Part made'
          value={fmtQty(partMade)}
          color={partMade > 0 ? 'orange' : undefined}
          hint='Jobs with more to make or to close'
        />
        <Figure
          label='Machine time open'
          value={minutes > 0 ? fmtMinutes(minutes) : runsLeft > 0 ? plural(runsLeft, 'run') : '0'}
          hint={
            minutes > 0 && untimed > 0
              ? `${plural(runsLeft, 'run')} · ${plural(untimed, 'job')} without a time`
              : `${plural(runsLeft, 'run')} still to do on open jobs`
          }
        />
        <Figure
          label='Due to make'
          value={fmtQty(due.length)}
          color={due.length > 0 ? 'orange' : undefined}
          hint='Parts short, even counting open jobs'
        />
      </SimpleGrid>

      <Stack gap='xs'>
        <Title order={5}>Open jobs</Title>
        {jobs.length === 0 ? (
          <Text size='sm' c='dimmed'>
            No job is open{machineId === null ? '' : ' on this machine'}.
          </Text>
        ) : (
          jobs.map((job) => (
            <JobCard
              key={job.build}
              context={context}
              slug={slug}
              job={job}
              permissions={permissions}
              setupNotes={notesOf(job.part)}
              showPart
              onChanged={reload}
            />
          ))
        )}
      </Stack>

      <Stack gap='xs'>
        <Title order={5}>Linked parts</Title>
        {parts.length === 0 ? (
          <Text size='sm' c='dimmed'>
            {machineId === null
              ? 'No part is linked to a machine yet. Use "Link a part", or the Workshop panel on a part page.'
              : 'No part is linked to this machine.'}
          </Text>
        ) : (
          <ScrollArea>
            <Table striped withTableBorder verticalSpacing={6} miw={960}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Part</Table.Th>
                  <Table.Th>Machine and files</Table.Th>
                  <Table.Th style={numCell}>In stock</Table.Th>
                  <Table.Th style={numCell}>Minimum</Table.Th>
                  <Table.Th style={numCell}>On its way</Table.Th>
                  <Table.Th style={numCell}>Needed</Table.Th>
                  <Table.Th>Now</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {parts.map((row) => {
                  const low = row.numbers.minimum > 0 && row.numbers.stock < row.numbers.minimum;
                  const files = row.link.files;
                  const blocked = row.link.file_missing || row.link.machine_missing;

                  return (
                    <Table.Tr key={row.part.pk}>
                      <Table.Td>
                        <AppLink context={context} to={partUrl(row.part.pk)}>
                          {row.part.name}
                        </AppLink>
                        {row.part.ipn && (
                          <Text size='xs' c='dimmed'>
                            {row.part.ipn}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Group gap={6} wrap='nowrap'>
                          <MachineBadge name={row.link.machine_name} kind={row.link.machine_kind} />
                          <Text size='sm' style={{ wordBreak: 'break-all' }}>
                            {files.length === 1 ? files[0].filename : plural(files.length, 'file')}
                          </Text>
                        </Group>
                        <Text size='xs' c='dimmed'>
                          {[
                            `${fmtQty(row.link.parts_per_run)} a run`,
                            row.link.run_minutes ? fmtMinutes(row.link.run_minutes) : '',
                            ...(files.length === 1 ? files[0].summary.facts.slice(0, 2) : [])
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </Text>
                      </Table.Td>
                      <Table.Td style={numCell}>
                        <Text size='sm' span c={low ? 'orange' : undefined} fw={low ? 600 : undefined}>
                          {fmtQty(row.numbers.stock)}
                        </Text>
                      </Table.Td>
                      <Table.Td style={numCell}>
                        {row.numbers.minimum > 0 ? fmtQty(row.numbers.minimum) : ''}
                      </Table.Td>
                      <Table.Td style={numCell}>
                        {row.numbers.incoming > 0 ? fmtQty(row.numbers.incoming) : ''}
                      </Table.Td>
                      <Table.Td style={numCell}>
                        {row.numbers.demand > 0 ? fmtQty(row.numbers.demand) : ''}
                      </Table.Td>
                      <Table.Td>{suggestionCell(row)}</Table.Td>
                      <Table.Td>
                        <Group gap={6} justify='flex-end' wrap='nowrap'>
                          {files.some((file) => !file.missing) && (
                            <DownloadButton
                              context={context}
                              url={`/plugin/${slug}/part/${row.part.pk}/download/`}
                              filename={
                                files.length === 1
                                  ? (files[0].filename ?? 'file')
                                  : `${row.part.name}-files.zip`
                              }
                              label={files.length === 1 ? 'File' : 'Files'}
                              size='compact-sm'
                            />
                          )}
                          {permissions.link && (
                            <Button
                              size='compact-sm'
                              variant='default'
                              leftSection={<IconPencil size={13} />}
                              onClick={() => setLinkRow(row)}
                            >
                              Link
                            </Button>
                          )}
                          {permissions.make && !blocked && (
                            <Button
                              size='compact-sm'
                              leftSection={<IconTools size={13} />}
                              onClick={() => setMakeRow(row)}
                            >
                              Make
                            </Button>
                          )}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Stack>

      {history.length > 0 && (
        <Stack gap='xs'>
          <Title order={5}>Finished jobs</Title>
          <ScrollArea>
            <Table striped withTableBorder verticalSpacing={6} miw={700}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Build order</Table.Th>
                  <Table.Th>Part</Table.Th>
                  <Table.Th>Machine</Table.Th>
                  <Table.Th>Date</Table.Th>
                  <Table.Th style={numCell}>Runs</Table.Th>
                  <Table.Th style={numCell}>Good parts</Table.Th>
                  <Table.Th>Result</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {history.map((job) => {
                  const state = JOB_STATE[job.summary.state] ?? JOB_STATE.done;

                  return (
                    <Table.Tr key={job.build}>
                      <Table.Td>
                        <AppLink context={context} to={buildUrl(job.build)}>
                          {job.reference}
                        </AppLink>
                      </Table.Td>
                      <Table.Td>
                        <AppLink context={context} to={partUrl(job.part)}>
                          {job.part_name}
                        </AppLink>
                      </Table.Td>
                      <Table.Td>{job.machine?.name ?? ''}</Table.Td>
                      <Table.Td>{fmtDate(job.created)}</Table.Td>
                      <Table.Td style={numCell}>{fmtQty(job.summary.runs_done)}</Table.Td>
                      <Table.Td style={numCell}>
                        {fmtQty(job.completed)} of {fmtQty(job.quantity)}
                      </Table.Td>
                      <Table.Td>
                        <Badge color={state.color} variant='light'>
                          {state.label}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Stack>
      )}

      <PartPicker
        context={context}
        opened={picking}
        onClose={() => setPicking(false)}
        onPicked={(part) => {
          const row = data.parts.find((entry) => entry.part.pk === part.pk);

          setPicking(false);

          // A part which is linked already opens with its link
          if (row) {
            setLinkRow(row);
          } else {
            setLinkPart(part);
          }
        }}
      />

      {(linkPart || linkRow) && (
        <LinkModal
          context={context}
          slug={slug}
          part={(linkRow?.part ?? linkPart) as PartLabel}
          link={linkRow?.link ?? null}
          canManageMachines={permissions.link}
          opened
          onClose={() => {
            setLinkPart(null);
            setLinkRow(null);
          }}
          onSaved={reload}
        />
      )}

      {makeRow && (
        <MakeModal
          context={context}
          slug={slug}
          part={makeRow.part}
          link={makeRow.link}
          suggested={makeRow.suggestion.quantity}
          opened
          onClose={() => setMakeRow(null)}
          onDone={reload}
        />
      )}

      <MachinesModal
        context={context}
        slug={slug}
        opened={managing}
        canEdit={permissions.link}
        onClose={() => setManaging(false)}
        onChanged={reload}
      />
    </Stack>
  );
}
