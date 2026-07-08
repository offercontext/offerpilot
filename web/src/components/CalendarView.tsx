import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  DeleteOutlined,
  EditOutlined,
  LeftOutlined,
  PlusOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { Button, Spin, Empty, Tag, Drawer, Popconfirm, Tooltip, message } from 'antd';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import type { CalendarEntry } from '@/types/calendar';
import ScheduleEventForm from '@/components/ScheduleEventForm';
import { deleteEvent, getEvent } from '@/services/events';
import { getCalendar } from '@/services/calendar';
import type { ScheduleEvent } from '@/types/event';
import { EVENT_TYPE_LABELS } from '@/types/event';
import styles from './CalendarView.module.css';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

interface CalendarViewProps {
  onOpenDetail: (app: Application) => void;
  applications: Application[];
}

export default function CalendarView({ onOpenDetail, applications }: CalendarViewProps) {
  const queryClient = useQueryClient();
  const [currentMonth, setCurrentMonth] = useState(() => dayjs().date(1));
  const [formOpen, setFormOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState<ScheduleEvent | null>(null);
  const [loadingEventId, setLoadingEventId] = useState<number | null>(null);
  const latestEditEventId = useRef<number | null>(null);
  const editRequestToken = useRef(0);
  const monthKey = currentMonth.format('YYYY-MM');

  const { data: rawEntries, isLoading } = useQuery({
    queryKey: ['calendar', monthKey],
    queryFn: () => getCalendar(monthKey),
  });
  // Backend serializes an empty []T as JSON `null`; coalesce so iteration is safe.
  const entries = rawEntries ?? [];

  // Group entries by date string for O(1) lookup per cell.
  const byDate = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>();
    for (const e of entries) {
      const list = map.get(e.date) ?? [];
      list.push(e);
      map.set(e.date, list);
    }
    return map;
  }, [entries]);

  // Build a 6x7 grid covering the month (Monday-start week).
  const grid = useMemo(() => {
    const start = currentMonth.startOf('month');
    // dayjs day: 0=Sun..6=Sat. Convert to Monday-start offset.
    const offset = (start.day() + 6) % 7;
    const gridStart = start.subtract(offset, 'day');
    const cells: dayjs.Dayjs[] = [];
    for (let i = 0; i < 42; i++) {
      cells.push(gridStart.add(i, 'day'));
    }
    return cells;
  }, [currentMonth]);

  const today = dayjs();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const selectedEntries = selectedDate ? byDate.get(selectedDate) ?? [] : [];

  const cancelPendingEdit = () => {
    editRequestToken.current += 1;
    latestEditEventId.current = null;
    setLoadingEventId(null);
  };

  const deleteMutation = useMutation({
    mutationFn: deleteEvent,
    onSuccess: (_data, deletedId) => {
      cancelPendingEdit();
      setFormOpen(false);
      setEditingEvent(null);
      message.success('日程已删除');
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
      if (selectedEntries.filter((entry) => entry.event_id !== deletedId).length === 0) {
        setSelectedDate(null);
      }
    },
    onError: () => message.error('删除日程失败'),
  });

  const editMutation = useMutation({
    mutationFn: ({ eventId }: { eventId: number; token: number }) => getEvent(eventId),
    onMutate: ({ eventId, token }) => {
      editRequestToken.current = token;
      latestEditEventId.current = eventId;
      setLoadingEventId(eventId);
      setEditingEvent(null);
    },
    onSuccess: (event, { token }) => {
      if (token !== editRequestToken.current || event.id !== latestEditEventId.current) return;
      setEditingEvent(event);
      setFormOpen(true);
    },
    onError: (_error, { eventId, token }) => {
      if (token !== editRequestToken.current || eventId !== latestEditEventId.current) return;
      message.error('获取日程失败');
    },
    onSettled: (_data, _error, { eventId, token }) => {
      if (token !== editRequestToken.current || eventId !== latestEditEventId.current) return;
      setLoadingEventId(null);
      latestEditEventId.current = null;
    },
  });

  const getEntryLabel = (entry: CalendarEntry) => {
    if (entry.event_type) return EVENT_TYPE_LABELS[entry.event_type];
    if (entry.type === 'applied') return '投递';
    if (entry.note_id) return '复盘';
    return entry.type === 'interview' ? '复盘' : EVENT_TYPE_LABELS[entry.type];
  };

  const getEntryTagColor = (entry: CalendarEntry) => {
    if (entry.event_type === 'written_test' || entry.type === 'written_test') return 'blue';
    if (entry.event_type === 'offer_step' || entry.type === 'offer_step') return 'orange';
    if (entry.event_type === 'deadline' || entry.type === 'deadline') return 'red';
    if (entry.event_type === 'custom' || entry.type === 'custom') return 'purple';
    if (entry.type === 'applied') return 'default';
    return 'green';
  };

  const getEntryChipText = (entry: CalendarEntry) => {
    const time = entry.scheduled_at ? `${dayjs(entry.scheduled_at).format('HH:mm')} ` : '';
    const label = getEntryLabel(entry);
    if (entry.event_type) {
      const company = entry.title.replace(` · ${label}`, '');
      const position = entry.subtitle ? ` · ${entry.subtitle}` : '';
      return `${time}${label} ${company}${position}`;
    }
    const position = entry.subtitle ? ` · ${entry.subtitle}` : '';
    return `${time}${label} ${entry.title}${position}`;
  };

  const getEntryKey = (entry: CalendarEntry, index: number) =>
    `${entry.type}-${entry.event_id ?? entry.note_id ?? entry.app_id}-${entry.scheduled_at ?? entry.date}-${index}`;

  const openEntry = (e: CalendarEntry) => {
    cancelPendingEdit();
    setSelectedDate(null);
    const app = applications.find((a) => a.id === e.app_id);
    if (app) onOpenDetail(app);
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.toolbar}>
        <Button
          shape="circle"
          icon={<LeftOutlined />}
          onClick={() => setCurrentMonth((m) => m.subtract(1, 'month'))}
        />
        <span className={styles.monthLabel}>{currentMonth.format('YYYY 年 M 月')}</span>
        <Button
          shape="circle"
          icon={<RightOutlined />}
          onClick={() => setCurrentMonth((m) => m.add(1, 'month'))}
        />
        <Button
          size="small"
          onClick={() => setCurrentMonth(dayjs().date(1))}
          style={{ marginLeft: 8 }}
        >
          今天
        </Button>
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          className={styles.createButton}
          onClick={() => {
            cancelPendingEdit();
            setEditingEvent(null);
            setFormOpen(true);
          }}
        >
          新建日程
        </Button>
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : (
        <>
          <div className={styles.weekHeader}>
            {WEEKDAYS.map((w) => (
              <div key={w} className={styles.weekCell}>
                {w}
              </div>
            ))}
          </div>
          <div className={styles.grid}>
            {grid.map((d) => {
              const ds = d.format('YYYY-MM-DD');
              const dayEntries = byDate.get(ds) ?? [];
              const inMonth = d.month() === currentMonth.month();
              const isToday = d.isSame(today, 'day');
              return (
                <div
                  key={ds}
                  className={[
                    styles.cell,
                    !inMonth ? styles.cellMuted : '',
                    isToday ? styles.cellToday : '',
                    dayEntries.length > 0 ? styles.cellActive : '',
                  ].join(' ')}
                  onClick={() => dayEntries.length > 0 && setSelectedDate(ds)}
                >
                  <div className={styles.dateNum}>{d.date()}</div>
                  {dayEntries.length > 0 && (
                    <div className={styles.entries}>
                      {dayEntries.slice(0, 3).map((entry, index) => (
                        <Tooltip
                          key={getEntryKey(entry, index)}
                          title={getEntryChipText(entry)}
                        >
                          <span className={styles.entryChip}>{getEntryChipText(entry)}</span>
                        </Tooltip>
                      ))}
                      {dayEntries.length > 3 && (
                        <span className={styles.moreCount}>+{dayEntries.length - 3}</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className={styles.legend}>
            <span className={styles.legendDot + ' ' + styles.dotSchedule} /> 日程
            <span className={styles.legendDot + ' ' + styles.dotInterview} style={{ marginLeft: 16 }} /> 复盘
            <span className={styles.legendDot + ' ' + styles.dotApplied} style={{ marginLeft: 16 }} /> 投递
          </div>
        </>
      )}

      <Drawer
        title={selectedDate ? dayjs(selectedDate).format('M月D日 记录') : ''}
        open={!!selectedDate}
        onClose={() => {
          cancelPendingEdit();
          setSelectedDate(null);
        }}
        width={360}
        destroyOnClose
      >
        {selectedEntries.length === 0 ? (
          <Empty description="这一天没有记录" />
        ) : (
          <div>
            {selectedEntries.map((e, i) => (
              <div
                key={getEntryKey(e, i)}
                className={[styles.entryItem, e.editable ? styles.entryItemStatic : ''].join(' ')}
                onClick={() => !e.editable && openEntry(e)}
              >
                <div className={styles.entryHeader}>
                  <div className={styles.entryTitleWrap}>
                    {e.scheduled_at && (
                      <span className={styles.entryTime}>{dayjs(e.scheduled_at).format('HH:mm')}</span>
                    )}
                    <strong className={styles.entryTitle}>{e.title}</strong>
                  </div>
                  <div className={styles.entryMeta}>
                    <Tag color={getEntryTagColor(e)}>{getEntryLabel(e)}</Tag>
                    {e.editable && (
                      <div className={styles.entryActions} onClick={(event) => event.stopPropagation()}>
                        <Tooltip title="编辑日程">
                          <Button
                            size="small"
                            type="text"
                            icon={<EditOutlined />}
                            disabled={editMutation.isPending}
                            loading={loadingEventId === e.event_id}
                            onClick={() => {
                              if (!e.event_id || editMutation.isPending) return;
                              const token = editRequestToken.current + 1;
                              editRequestToken.current = token;
                              editMutation.mutate({
                                eventId: e.event_id,
                                token,
                              });
                            }}
                          />
                        </Tooltip>
                        <Popconfirm
                          title="删除日程"
                          description="确定删除这个日程吗？"
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true, loading: deleteMutation.isPending }}
                          onConfirm={() => {
                            cancelPendingEdit();
                            if (e.event_id) deleteMutation.mutate(e.event_id);
                          }}
                        >
                          <Tooltip title="删除日程">
                            <Button
                              size="small"
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                            />
                          </Tooltip>
                        </Popconfirm>
                      </div>
                    )}
                  </div>
                </div>
                {e.subtitle && <div className={styles.entrySubtitle}>{e.subtitle}</div>}
                {e.location && <div className={styles.entryLocation}>{e.location}</div>}
              </div>
            ))}
            <p style={{ marginTop: 12, color: '#94a3b8', fontSize: 12 }}>
              点击投递或复盘记录可打开对应投递详情。
            </p>
          </div>
        )}
      </Drawer>
      <ScheduleEventForm
        open={formOpen}
        applications={applications}
        event={editingEvent ?? undefined}
        onClose={() => {
          cancelPendingEdit();
          setFormOpen(false);
          setEditingEvent(null);
        }}
      />
    </div>
  );
}
