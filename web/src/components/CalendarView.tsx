import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Button, Spin, Empty, Tag, Drawer, Tooltip } from 'antd';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import type { CalendarEntry } from '@/types/calendar';
import { getCalendar } from '@/services/calendar';
import styles from './CalendarView.module.css';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

interface CalendarViewProps {
  onOpenDetail: (app: Application) => void;
  applications: Application[];
}

export default function CalendarView({ onOpenDetail, applications }: CalendarViewProps) {
  const [currentMonth, setCurrentMonth] = useState(() => dayjs().date(1));
  const monthKey = currentMonth.format('YYYY-MM');

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['calendar', monthKey],
    queryFn: () => getCalendar(monthKey),
  });

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

  const openEntry = (e: CalendarEntry) => {
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
              const hasInterview = dayEntries.some((e) => e.type === 'interview');
              const hasApplied = dayEntries.some((e) => e.type === 'applied');
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
                    <div className={styles.dots}>
                      {hasInterview && <span className={styles.dotInterview} />}
                      {hasApplied && <span className={styles.dotApplied} />}
                      {dayEntries.length > 1 && (
                        <Tooltip title={`${dayEntries.length} 条记录`}>
                          <span className={styles.count}>{dayEntries.length}</span>
                        </Tooltip>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className={styles.legend}>
            <span className={styles.legendDot + ' ' + styles.dotInterview} /> 面试复盘
            <span className={styles.legendDot + ' ' + styles.dotApplied} style={{ marginLeft: 16 }} /> 投递记录
          </div>
        </>
      )}

      <Drawer
        title={selectedDate ? dayjs(selectedDate).format('M月D日 记录') : ''}
        open={!!selectedDate}
        onClose={() => setSelectedDate(null)}
        width={360}
        destroyOnClose
      >
        {selectedEntries.length === 0 ? (
          <Empty description="这一天没有记录" />
        ) : (
          <div>
            {selectedEntries.map((e, i) => (
              <div
                key={i}
                className={styles.entryItem}
                onClick={() => openEntry(e)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <strong>{e.title}</strong>
                  <Tag color={e.type === 'interview' ? 'green' : 'default'}>
                    {e.type === 'interview' ? '面试' : '投递'}
                  </Tag>
                </div>
                {e.subtitle && <div style={{ color: '#64748b', fontSize: 13 }}>{e.subtitle}</div>}
              </div>
            ))}
            <p style={{ marginTop: 12, color: '#94a3b8', fontSize: 12 }}>
              点击任意条目可打开对应投递详情。
            </p>
          </div>
        )}
      </Drawer>
    </div>
  );
}