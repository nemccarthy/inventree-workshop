import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title
} from '@mantine/core';
import { IconLink, IconPencil, IconRefresh, IconTools } from '@tabler/icons-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { LinkModal } from './LinkModal';
import {
  JOB_STATE,
  apiData,
  apiError,
  fmtDate,
  fmtMaterial,
  fmtMinutes,
  fmtQty,
  plural
} from './format';
import type { Job, Link, Material, Numbers, PartData, Suggestion } from './types';
import {
  AppLink,
  DownloadButton,
  Figure,
  FileDetails,
  JobCard,
  MachineBadge,
  MakeModal,
  Preview,
  buildUrl,
  partUrl
} from './ui';

/** Whether more of the part should be made now, in a sentence */
export function suggestionSentence(
  link: Link,
  numbers: Numbers,
  suggestion: Suggestion | null
): { text: string; color?: string } {
  if (suggestion && suggestion.runs > 0) {
    const why =
      suggestion.reason === 'build_demand'
        ? 'build orders need more than there is'
        : `stock is below the minimum of ${fmtQty(numbers.minimum)}`;

    return {
      text: `Time to make more: ${why}. ${plural(suggestion.runs, 'run')} would bring it to ${fmtQty(
        suggestion.projected + suggestion.quantity
      )}.`,
      color: 'orange'
    };
  }

  if (numbers.minimum > 0) {
    return {
      text: `Making more is suggested when stock, with what is on its way and less what build orders need, falls below ${fmtQty(
        numbers.minimum
      )}${
        link.restock_to && link.restock_to > numbers.minimum
          ? ` (then up to ${fmtQty(link.restock_to)})`
          : ''
      }.`
    };
  }

  return {
    text: 'No minimum stock is set on this part, so making more is only suggested when build orders need more than there is.'
  };
}

/** What one run uses, from the bill of materials */
function MaterialLine({
  context,
  materials,
  perRun
}: Readonly<{ context: InvenTreePluginContext; materials: Material[]; perRun: number }>) {
  const taken = materials.filter((material) => material.taken);

  if (taken.length === 0) {
    return (
      <Text size='sm' c='dimmed'>
        No material is taken from stock. To have the sheet or blank it is made from taken when
        parts are booked, add it to the bill of materials of this part.
      </Text>
    );
  }

  return (
    <Text size='sm'>
      One run uses{' '}
      {taken.map((material, index) => (
        <span key={material.part}>
          {index > 0 ? ', ' : ''}
          {fmtMaterial(Math.round(material.per_part * perRun * 10000) / 10000, material.units)}{' '}
          <AppLink context={context} to={partUrl(material.part)}>
            {material.name}
          </AppLink>
        </span>
      ))}
      , taken from stock when parts are booked.
    </Text>
  );
}

function HistoryTable({
  context,
  jobs
}: Readonly<{ context: InvenTreePluginContext; jobs: Job[] }>) {
  return (
    <Table striped withTableBorder verticalSpacing={6}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Build order</Table.Th>
          <Table.Th>Date</Table.Th>
          <Table.Th>Machine</Table.Th>
          <Table.Th style={{ textAlign: 'right' }}>Runs</Table.Th>
          <Table.Th style={{ textAlign: 'right' }}>Good parts</Table.Th>
          <Table.Th>Result</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {jobs.map((job) => {
          const state = JOB_STATE[job.summary.state] ?? JOB_STATE.done;

          return (
            <Table.Tr key={job.build}>
              <Table.Td>
                <AppLink context={context} to={buildUrl(job.build)}>
                  {job.reference}
                </AppLink>
              </Table.Td>
              <Table.Td>{fmtDate(job.created)}</Table.Td>
              <Table.Td>{job.machine?.name ?? ''}</Table.Td>
              <Table.Td style={{ textAlign: 'right' }}>{fmtQty(job.summary.runs_done)}</Table.Td>
              <Table.Td style={{ textAlign: 'right' }}>
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
  );
}

/** Workshop panel on a part page */
export function WorkshopPartPanel({ context }: Readonly<{ context: InvenTreePluginContext }>) {
  const api = useRef(context.api);
  api.current = context.api;

  const partId: number | null = context.context?.part_id ?? context.id ?? null;
  const slug: string = context.context?.slug ?? 'workshop';

  const [data, setData] = useState<PartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [linking, setLinking] = useState(false);
  const [making, setMaking] = useState(false);

  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    if (partId === null || partId === undefined) {
      setLoading(false);
      setError('No part is associated with this page');
      return;
    }

    let cancelled = false;

    setLoading(true);
    setError(null);

    api.current
      .get(`/plugin/${slug}/part/${partId}/`)
      .then((response) => {
        if (!cancelled) {
          setData(apiData<PartData>(response, 'part'));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(apiError(err, 'Could not load the workshop data for this part'));
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
  }, [partId, slug, reloadKey]);

  if (!data) {
    return error ? (
      <Alert color='red' title='Could not load the workshop data'>
        {error}
      </Alert>
    ) : (
      <Center h={200}>
        <Loader />
      </Center>
    );
  }

  const { part, link, numbers, suggestion, permissions } = data;

  const modal = (
    <LinkModal
      context={context}
      slug={slug}
      part={part}
      link={link}
      canManageMachines={permissions.link}
      opened={linking}
      onClose={() => setLinking(false)}
      onSaved={reload}
    />
  );

  if (!link) {
    return (
      <Stack gap='md' align='flex-start'>
        {error && <Alert color='red'>{error}</Alert>}
        <Text>
          This part is not linked to a workshop machine. If it is made in-house from a file (cut
          on the laser, milled on the CNC), link it to its machine and its files to keep them
          with the part and book runs into stock from here.
        </Text>
        {permissions.link ? (
          <Button leftSection={<IconLink size={16} />} onClick={() => setLinking(true)}>
            Link to a machine
          </Button>
        ) : (
          <Text size='sm' c='dimmed'>
            You need permission to change parts to link it.
          </Text>
        )}
        {data.jobs.length > 0 && (
          <Stack gap='xs' w='100%'>
            <Title order={5}>Jobs</Title>
            {data.jobs.map((job) => (
              <JobCard
                key={job.build}
                context={context}
                slug={slug}
                job={job}
                permissions={permissions}
                onChanged={reload}
              />
            ))}
          </Stack>
        )}
        {data.history.length > 0 && <HistoryTable context={context} jobs={data.history} />}
        {modal}
      </Stack>
    );
  }

  const sentence = suggestionSentence(link, numbers, suggestion);
  const projected = numbers.stock + numbers.incoming - numbers.demand;
  const blocked = link.file_missing || link.machine_missing;
  const cover = link.files.find((file) => file.summary.has_cover && !file.missing) ?? null;
  const several = link.files.length > 1;

  return (
    <Stack gap='md'>
      {error && <Alert color='red'>{error}</Alert>}

      {link.machine_missing && (
        <Alert color='red' title='The machine of this part was removed'>
          Edit the link and choose the machine which makes it now. No job can be raised until
          then.
        </Alert>
      )}

      {link.file_missing && (
        <Alert color='red' title={several ? 'A file of this part is gone' : 'The file is gone'}>
          {link.files
            .filter((file) => file.missing)
            .map((file) => `"${file.filename}"`)
            .join(', ')}{' '}
          {link.files.filter((file) => file.missing).length === 1 ? 'is' : 'are'} no longer
          attached to this part. Edit the link to choose or upload again. No job can be raised
          until then.
        </Alert>
      )}

      {link.file_changed && !link.file_missing && (
        <Alert color='yellow' title='A file was changed in storage'>
          {link.files
            .filter((file) => file.changed)
            .map((file) => `"${file.filename}"`)
            .join(', ')}{' '}
          is no longer the file which was linked. Edit the link and save it to read it again.
        </Alert>
      )}

      <Paper withBorder p='sm'>
        <Group justify='space-between' align='flex-start' wrap='wrap'>
          <Group gap='md' wrap='nowrap' align='flex-start' style={{ flex: 1, minWidth: 280 }}>
            {cover && (
              <Preview
                context={context}
                url={`/plugin/${slug}/part/${part.pk}/preview/?attachment=${cover.attachment}`}
              />
            )}
            <Stack gap={6} style={{ minWidth: 0 }}>
              <Group gap='xs' wrap='wrap'>
                <Text size='sm'>Made on</Text>
                <MachineBadge name={link.machine_name} kind={link.machine_kind} />
                <Text size='sm'>
                  {[
                    `${plural(link.parts_per_run, 'good part')} from one run`,
                    link.run_minutes ? `${fmtMinutes(link.run_minutes)} a run` : '',
                    link.destination_name ? `to ${link.destination_name}` : ''
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </Text>
              </Group>
              {link.files.map((file, index) => (
                <Stack gap={2} key={file.attachment}>
                  <Text fw={600} size='sm' style={{ wordBreak: 'break-all' }}>
                    {several ? `${index + 1}. ` : ''}
                    {file.label ? `${file.label}: ` : ''}
                    {file.filename}
                  </Text>
                  {file.missing ? (
                    <Text size='sm' c='red'>
                      No longer attached to the part.
                    </Text>
                  ) : (
                    <FileDetails summary={file.summary} />
                  )}
                </Stack>
              ))}
            </Stack>
          </Group>
          <Group gap='xs'>
            <Button
              variant='default'
              size='xs'
              leftSection={<IconRefresh size={14} />}
              loading={loading}
              onClick={reload}
            >
              Refresh
            </Button>
            {permissions.link && (
              <Button
                variant='default'
                size='xs'
                leftSection={<IconPencil size={14} />}
                onClick={() => setLinking(true)}
              >
                Edit link
              </Button>
            )}
            {link.files.some((file) => !file.missing) && (
              <DownloadButton
                context={context}
                url={`/plugin/${slug}/part/${part.pk}/download/`}
                filename={several ? `${part.name}-files.zip` : (link.files[0].filename ?? 'file')}
                label={several ? `Download the ${link.files.length} files` : 'Download the file'}
              />
            )}
            {permissions.make && !blocked && (
              <Button size='xs' leftSection={<IconTools size={14} />} onClick={() => setMaking(true)}>
                Make
              </Button>
            )}
          </Group>
        </Group>
        {(link.setup_notes || link.machine_notes) && (
          <Stack gap={2} mt='xs'>
            {link.machine_notes && (
              <Text size='sm' style={{ whiteSpace: 'pre-wrap' }}>
                <Text span fw={600} size='sm'>
                  {link.machine_name}:{' '}
                </Text>
                {link.machine_notes}
              </Text>
            )}
            {link.setup_notes && (
              <Text size='sm' style={{ whiteSpace: 'pre-wrap' }}>
                <Text span fw={600} size='sm'>
                  Setup:{' '}
                </Text>
                {link.setup_notes}
              </Text>
            )}
          </Stack>
        )}
      </Paper>

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Figure
          label='In stock'
          value={fmtQty(numbers.stock)}
          color={numbers.minimum > 0 && numbers.stock < numbers.minimum ? 'orange' : undefined}
          hint={numbers.minimum > 0 ? `Minimum ${fmtQty(numbers.minimum)}` : 'No minimum set'}
        />
        <Figure
          label='On its way'
          value={fmtQty(numbers.incoming)}
          hint={
            numbers.incoming > numbers.incoming_jobs
              ? `${fmtQty(numbers.incoming - numbers.incoming_jobs)} on other build orders`
              : 'On open workshop jobs'
          }
        />
        <Figure
          label='Needed by build orders'
          value={fmtQty(numbers.demand)}
          hint={
            numbers.demand_builds.length > 0
              ? numbers.demand_builds
                  .slice(0, 3)
                  .map((build) => build.reference)
                  .join(', ') + (numbers.demand_builds.length > 3 ? ', ...' : '')
              : data.include_pending
                ? 'Open build orders'
                : 'Build orders in production'
          }
        />
        <Figure
          label='Left over'
          value={fmtQty(projected)}
          color={projected < 0 ? 'red' : undefined}
          hint='In stock + on its way - needed'
        />
      </SimpleGrid>

      <Stack gap={4}>
        <Text size='sm' c={sentence.color ?? 'dimmed'} fw={sentence.color ? 600 : undefined}>
          {sentence.text}
        </Text>
        <MaterialLine context={context} materials={data.materials} perRun={link.parts_per_run} />
      </Stack>

      {data.jobs.length > 0 ? (
        <Stack gap='xs'>
          <Title order={5}>Jobs</Title>
          {data.jobs.map((job) => (
            <JobCard
              key={job.build}
              context={context}
              slug={slug}
              job={job}
              permissions={permissions}
              onChanged={reload}
            />
          ))}
        </Stack>
      ) : (
        <Text size='sm' c='dimmed'>
          No job is open for this part.
        </Text>
      )}

      {data.history.length > 0 && (
        <Stack gap='xs'>
          <Title order={5}>Finished jobs</Title>
          <HistoryTable context={context} jobs={data.history} />
        </Stack>
      )}

      {modal}
      <MakeModal
        context={context}
        slug={slug}
        part={part}
        link={link}
        suggested={suggestion?.quantity}
        opened={making}
        onClose={() => setMaking(false)}
        onDone={reload}
      />
    </Stack>
  );
}
