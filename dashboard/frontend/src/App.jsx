import React, { useState, useEffect, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, ReferenceLine } from 'recharts';
import { Activity, TrendingUp, BarChart3, Clock, AlertCircle, ChevronDown, ChevronUp, Cpu, LayoutDashboard, BrainCircuit, Table as TableIcon, Zap, Target, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const App = () => {
    const [sessions, setSessions] = useState([]);
    const [selectedSession, setSelectedSession] = useState(null);
    const [activeTab, setActiveTab] = useState('analytics');

    const [equity, setEquity] = useState([]);
    const [trades, setTrades] = useState([]);
    const [logs, setLogs] = useState([]);
    const [audits, setAudits] = useState([]);
    const [loading, setLoading] = useState(true);

    const [hoveredTradeTime, setHoveredTradeTime] = useState(null);

    // Fetch sessions
    useEffect(() => {
        const fetchSessions = async () => {
            try {
                const res = await fetch('/api/sessions');
                const data = await res.json();
                setSessions(data);
                if (data.length > 0 && !selectedSession) {
                    setSelectedSession(data[0].session_id);
                }
            } catch (err) {
                console.error("Failed to fetch sessions", err);
            } finally {
                setLoading(false);
            }
        };
        fetchSessions();
        const interval = setInterval(fetchSessions, 15000);
        return () => clearInterval(interval);
    }, []);

    // Fetch session details
    useEffect(() => {
        if (!selectedSession) return;
        const fetchData = async () => {
            try {
                const [equityRes, tradesRes, logsRes, auditsRes] = await Promise.all([
                    fetch(`/api/equity/${selectedSession}`),
                    fetch(`/api/trades/${selectedSession}`),
                    fetch(`/api/logs/${selectedSession}`),
                    fetch(`/api/eod-audits/${selectedSession}`)
                ]);

                if (equityRes.ok) setEquity(await equityRes.json());
                if (tradesRes.ok) setTrades(await tradesRes.json());
                if (logsRes.ok) setLogs(await logsRes.json());
                if (auditsRes.ok) setAudits(await auditsRes.json());

            } catch (err) {
                console.error("Failed to fetch session details", err);
            }
        };
        fetchData();
        const interval = setInterval(fetchData, 10000);
        return () => clearInterval(interval);
    }, [selectedSession]);

    const stats = useMemo(() => {
        return sessions.find(s => s.session_id === selectedSession) || { total_pnl: 0, trade_count: 0, symbol: 'BEAST' };
    }, [sessions, selectedSession]);

    const winRate = useMemo(() => {
        return trades.length > 0
            ? ((trades.filter(t => t.pnl > 0).length / trades.length) * 100).toFixed(1)
            : 0;
    }, [trades]);

    return (
        <div className="min-h-screen bg-oled text-gray-200 font-sans selection:bg-tv-green selection:text-black antialiased">
            <div className="w-full mx-auto p-4 md:p-6 lg:p-8 space-y-6 flex flex-col items-stretch">

                {/* TradingView Style Top Bar - Fluid */}
                <header className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 py-3 px-4 bg-tv-bg border border-white/[0.05] rounded-lg shadow-xl shrink-0">
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2">
                            <div className="w-6 h-6 bg-tv-green rounded flex items-center justify-center">
                                <Zap size={14} className="text-white fill-current" />
                            </div>
                            <h1 className="text-base font-bold tracking-tight uppercase whitespace-nowrap">
                                Beast<span className="text-tv-green">Terminal</span>
                            </h1>
                        </div>

                        <div className="h-4 w-[1px] bg-white/10 hidden lg:block" />

                        <div className="flex bg-white/[0.02] p-0.5 rounded border border-white/[0.05]">
                            <NavTab active={activeTab === 'analytics'} onClick={() => setActiveTab('analytics')} label="MARKET_SPECTRUM" />
                            <NavTab active={activeTab === 'ai'} onClick={() => setActiveTab('ai')} label="NEURAL_LOGS" />
                        </div>
                    </div>

                    <div className="flex items-center gap-6 flex-wrap lg:flex-nowrap">
                        <div className="relative group min-w-[320px] flex-1 lg:flex-none">
                            <span className="absolute -top-4 left-1 text-[8px] font-black text-tv-green uppercase tracking-widest">Selected Session</span>
                            <select
                                value={selectedSession || ''}
                                onChange={(e) => setSelectedSession(e.target.value)}
                                className="appearance-none w-full bg-oled border border-white/10 rounded px-4 py-1.5 pr-10 outline-none focus:border-tv-green/50 text-[11px] transition-all font-mono font-bold hover:bg-white/[0.02] cursor-pointer"
                            >
                                {sessions.map(s => (
                                    <option key={s.session_id} value={s.session_id} className="bg-tv-bg py-2">
                                        {s.symbol ? `${s.symbol} [${s.start_date} → ${s.end_date}]` : s.session_id}
                                    </option>
                                ))}
                            </select>
                            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500" size={14} />
                        </div>

                        <div className="h-4 w-[1px] bg-white/10 hidden lg:block" />

                        <div className="flex items-center gap-4 text-[10px] font-mono font-bold whitespace-nowrap">
                            <div className="flex items-center gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-tv-green animate-pulse" />
                                <span className="text-gray-500 uppercase">Live Engine</span>
                            </div>
                            <span className="text-white">UTC+5:30</span>
                        </div>
                    </div>
                </header>

                {/* Floating Quick Stats - Fluid Grid */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 shrink-0">
                    <MetricSlot label="NET_PNL" value={stats.total_pnl.toFixed(1)} unit="pts" color={stats.total_pnl >= 0 ? 'tv-green' : 'tv-red'} />
                    <MetricSlot label="WIN_RATE" value={winRate} unit="%" color="tv-green" />
                    <MetricSlot label="SESSIONS" value={stats.trade_count} unit="ops" color="white" />
                    <MetricSlot label="LATENCY" value="0" unit="ms" color="accent-cyan" />
                    <MetricSlot label="STREAK" value="0" unit="max" color="accent-purple" />
                    <MetricSlot label="DRAWDOWN" value="0.0" unit="%" color="tv-red" />
                </div>

                <AnimatePresence mode="wait">
                    {activeTab === 'analytics' ? (
                        <motion.div
                            key="analytics"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="flex flex-col gap-5 w-full"
                        >
                            {/* Main TV Chart Area - Full Width & Taller */}
                            <div className="bg-tv-bg border border-white/[0.05] rounded-xl shadow-2xl relative overflow-hidden h-[720px] w-full shrink-0">
                                {/* Chart Overlay (Top Left Floating) */}
                                <div className="absolute top-8 left-8 z-20 space-y-2 pointer-events-none">
                                    <div className="flex items-center gap-4">
                                        <h2 className="text-2xl font-black font-mono tracking-tighter text-white">
                                            {stats.symbol || 'BEAST'}<span className="text-gray-500 text-base ml-3 font-normal">EQUITY_CURVE</span>
                                        </h2>
                                        <span className="bg-tv-green/10 text-tv-green text-[10px] px-2 py-1 rounded font-black border border-tv-green/20">REAL_TIME</span>
                                    </div>
                                    <p className="text-[11px] font-bold text-gray-400 font-mono tracking-[0.2em] uppercase">
                                        Pipeline: NEURAL_ENGINE | Scale: LINEAR
                                    </p>
                                </div>

                                {/* Chart Tooltip / Crosshair Info - Persistent Style */}
                                <div className="absolute top-4 right-8 z-20 pointer-events-none flex gap-10">
                                    <div className="text-right">
                                        <p className="text-[9px] font-black text-gray-600 uppercase tracking-widest">Aggregate_Alpha</p>
                                        <p className={`text-xl font-black font-mono ${stats.total_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'}`}>
                                            {stats.total_pnl.toFixed(2)} pts
                                        </p>
                                    </div>
                                </div>

                                <div className="absolute inset-0 pt-28 pb-12 pr-4 z-10">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <AreaChart data={equity} margin={{ right: 20 }}>
                                            <defs>
                                                <linearGradient id="tvGradient" x1="0" y1="0" x2="0" y2="1">
                                                    <stop offset="0%" stopColor="#22ab94" stopOpacity={0.2} />
                                                    <stop offset="100%" stopColor="#22ab94" stopOpacity={0} />
                                                </linearGradient>
                                            </defs>
                                            <CartesianGrid strokeDasharray="0 0" stroke="#2a2e39" vertical={true} horizontal={true} />
                                            <XAxis dataKey="time" hide />
                                            <YAxis
                                                stroke="#2a2e39"
                                                fontSize={11}
                                                tickFormatter={(val) => `${val}`}
                                                orientation="right"
                                                axisLine={true}
                                                tickLine={true}
                                                tick={{ fill: '#808080', fontSize: 10, fontWeight: 'bold' }}
                                                domain={['auto', 'auto']}
                                            />
                                            <Tooltip content={<TVTooltip />} cursor={{ stroke: '#ffffff30', strokeWidth: 1.5 }} />
                                            <Area
                                                type="monotone"
                                                dataKey="pnl"
                                                stroke="#22ab94"
                                                strokeWidth={3}
                                                fill="url(#tvGradient)"
                                                strokeLinecap="round"
                                                animationDuration={1500}
                                            />
                                            {hoveredTradeTime && (
                                                <ReferenceLine x={hoveredTradeTime} stroke="#00FFFF" strokeWidth={1} strokeDasharray="6 6" />
                                            )}
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            {/* Secondary Layer - Grid for Ledger & Matrix */}
                            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 w-full">
                                {/* Ledger View */}
                                <div className="lg:col-span-8 bg-tv-bg border border-white/[0.05] rounded-xl overflow-hidden shadow-xl">
                                    <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.05] bg-white/[0.01]">
                                        <h3 className="text-[11px] font-black tracking-[0.4em] text-gray-400 uppercase">ORDER_EXECUTION_FLOW</h3>
                                        <div className="flex gap-4">
                                            <div className="flex items-center gap-2 text-[10px] font-black text-tv-green uppercase tracking-widest">
                                                <div className="w-2 h-2 rounded-full bg-tv-green" /> Verified_Logic
                                            </div>
                                        </div>
                                    </div>
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-left border-collapse min-w-[800px]">
                                            <thead>
                                                <tr className="text-[10px] font-black tracking-[0.3em] text-gray-500 uppercase bg-black/30">
                                                    <th className="px-8 py-4">UTC_EXPIRY</th>
                                                    <th className="px-8 py-4 text-center">SIDE</th>
                                                    <th className="px-8 py-4">BASE_ENTRY</th>
                                                    <th className="px-8 py-4">BASE_EXIT</th>
                                                    <th className="px-8 py-4 text-tv-green">PNL_DELTA</th>
                                                    <th className="px-8 py-4">LOGIC_GATE</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-white/[0.03]">
                                                {trades.slice().reverse().map((trade, i) => (
                                                    <tr
                                                        key={i}
                                                        className="group transition-all hover:bg-white/[0.02]"
                                                        onMouseEnter={() => setHoveredTradeTime(trade.exit_time)}
                                                        onMouseLeave={() => setHoveredTradeTime(null)}
                                                    >
                                                        <td className="px-8 py-5 font-mono text-[11px] text-gray-500">
                                                            {new Date(trade.exit_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                        </td>
                                                        <td className="px-8 py-5 text-center">
                                                            <span className={`px-3 py-1 rounded-sm text-[9px] font-black tracking-widest uppercase border ${trade.side === 'CALL' ? 'border-tv-green/40 text-tv-green bg-tv-green/5' : 'border-tv-red/40 text-tv-red bg-tv-red/5'
                                                                }`}>
                                                                {trade.side}
                                                            </span>
                                                        </td>
                                                        <td className="px-8 py-5 font-mono text-[12px] text-gray-300 font-bold">{trade.entry_price.toLocaleString(undefined, { minimumFractionDigits: 1 })}</td>
                                                        <td className="px-8 py-5 font-mono text-[12px] text-gray-300 font-bold">{trade.exit_price.toLocaleString(undefined, { minimumFractionDigits: 1 })}</td>
                                                        <td className={`px-8 py-5 font-mono font-black text-[13px] ${trade.pnl >= 0 ? 'text-tv-green' : 'text-tv-red'}`}>
                                                            {trade.pnl > 0 ? '+' : ''}{trade.pnl.toFixed(1)}
                                                        </td>
                                                        <td className="px-8 py-5 text-[12px] text-gray-400 font-medium group-hover:text-white transition-colors">
                                                            {trade.reason}
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                        {trades.length === 0 && <div className="py-24 text-center text-gray-600 font-mono text-[11px] uppercase tracking-[0.5em] animate-pulse">Scanning Decision Flow...</div>}
                                    </div>
                                </div>

                                {/* Side Intelligence Panel */}
                                <div className="lg:col-span-4 bg-tv-bg border border-white/[0.05] rounded-xl h-[800px] flex flex-col shadow-xl">
                                    <div className="px-8 py-5 border-b border-white/[0.05] flex items-center justify-between bg-white/[0.01]">
                                        <h3 className="text-[11px] font-black tracking-[0.4em] text-gray-400 uppercase">NEURAL_MATRIX</h3>
                                        <BrainCircuit size={16} className="text-tv-green" />
                                    </div>

                                    <div className="flex-1 overflow-y-auto space-y-px custom-scrollbar p-1">
                                        {logs.map((log, i) => (
                                            <div key={i} className="px-8 py-6 border-b border-white/[0.02] hover:bg-white/[0.02] transition-all group">
                                                <div className="flex justify-between items-center text-[10px] font-black uppercase mb-3">
                                                    <span className={`tracking-widest ${log.event_type === 'MORNING' ? 'text-accent-cyan' :
                                                        log.event_type === 'TACTICAL' ? 'text-accent-purple' : 'text-tv-green'
                                                        }`}>[{log.event_type}]</span>
                                                    <span className="font-mono text-gray-600">{new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                                </div>
                                                <p className="text-[12px] text-gray-400 leading-relaxed font-medium group-hover:text-gray-200 transition-colors">
                                                    {parseContent(log.content)}
                                                </p>
                                            </div>
                                        ))}
                                        {logs.length === 0 && <div className="py-24 text-center text-gray-600 font-mono text-[10px] uppercase tracking-[0.4em]">Listening for Neural Patterns...</div>}
                                    </div>
                                </div>
                            </div>
                        </motion.div>
                    ) : (
                        <motion.div
                            key="ai"
                            initial={{ opacity: 0, y: 15 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -15 }}
                            className="space-y-6 w-full"
                        >
                            {audits.map((audit, i) => (
                                <div key={i} className="bg-tv-bg border border-white/[0.05] rounded-lg p-5 hover:border-tv-green/30 transition-all shadow-xl group w-full overflow-visible">
                                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 border-b border-white/[0.05] pb-4">
                                        <div className="flex items-center gap-10">
                                            <div className="flex flex-col">
                                                <span className="text-[8px] font-black text-gray-600 uppercase tracking-[0.3em] mb-1">AUDIT_CYCLE</span>
                                                <h2 className="text-3xl font-black italic tracking-tighter text-white font-mono leading-none">
                                                    {audit.date.split('-').slice(1).join('/')}
                                                </h2>
                                            </div>

                                            <div className="flex gap-12 font-mono">
                                                <div>
                                                    <p className="text-[8px] font-black text-gray-600 uppercase tracking-widest mb-1">TOTAL_OPS</p>
                                                    <p className="text-xl font-black">{audit.trade_count}</p>
                                                </div>
                                                <div>
                                                    <p className="text-[8px] font-black text-gray-600 uppercase tracking-widest mb-1">NET_ALPHA</p>
                                                    <p className={`text-xl font-black ${audit.total_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'}`}>
                                                        {audit.total_pnl >= 0 ? '+' : ''}{audit.total_pnl.toFixed(1)}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="flex gap-10 text-right">
                                            <div className="space-y-1">
                                                <p className="text-[8px] font-black text-gray-600 tracking-widest uppercase">Peak Win</p>
                                                <p className="text-xs font-black text-tv-green font-mono">+{audit.highest_win.toFixed(1)}</p>
                                            </div>
                                            <div className="space-y-1">
                                                <p className="text-[8px] font-black text-gray-600 tracking-widest uppercase">Max Loss</p>
                                                <p className="text-xs font-black text-tv-red font-mono">{audit.highest_loss.toFixed(1)}</p>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="mt-4 flex flex-col md:flex-row gap-4 items-start md:items-center">
                                        <div className="flex items-center gap-2 shrink-0">
                                            <BrainCircuit size={14} className="text-tv-green" />
                                            <h4 className="text-[9px] font-black tracking-[0.4em] text-white uppercase italic">Neural_Result:</h4>
                                        </div>

                                        <div className="text-gray-300 text-[13px] leading-relaxed italic font-medium whitespace-pre-wrap break-words overflow-visible flex-1">
                                            "{audit.nugget}"
                                        </div>
                                    </div>
                                </div>
                            ))}

                            {audits.length === 0 && (
                                <div className="py-48 text-center flex flex-col items-center gap-6 opacity-30">
                                    <Activity size={64} className="animate-pulse" />
                                    <p className="font-mono text-[12px] uppercase tracking-[0.6em] font-black text-tv-green">Historical Vault Empty</p>
                                </div>
                            )}
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </div>
    );
};

// Sub-components
const NavTab = ({ active, onClick, label }) => (
    <button
        onClick={onClick}
        className={`px-6 py-2 rounded text-[10px] font-black tracking-widest transition-all uppercase ${active ? 'bg-white/10 text-white border border-white/10 shadow-lg' : 'text-gray-500 hover:text-gray-300'
            }`}
    >
        {label}
    </button>
);

const MetricSlot = ({ label, value, unit, color }) => (
    <div className="bg-tv-bg border border-white/[0.05] px-6 py-4 rounded-xl flex flex-col gap-2 hover:border-white/20 transition-all cursor-default group shadow-sm">
        <span className="text-gray-600 text-[9px] font-black tracking-[0.2em] uppercase group-hover:text-gray-400 transition-colors">{label}</span>
        <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-black font-mono tracking-tighter text-${color}`}>{value}</span>
            <span className="text-[10px] font-bold text-gray-700 italic font-mono uppercase">{unit}</span>
        </div>
    </div>
);

const TVTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
        const data = payload[0].payload;
        return (
            <div className="bg-tv-bg border border-gray-700 p-5 rounded-lg shadow-2xl relative min-w-[180px]">
                <div className="absolute top-0 left-0 w-[3px] h-full bg-tv-green rounded-l" />
                <p className="text-[9px] font-black text-gray-500 uppercase tracking-widest mb-2 italic font-mono">{data.time}</p>
                <div className="flex items-baseline gap-3">
                    <p className="text-2xl font-black font-mono text-tv-green">{payload[0].value.toFixed(2)}</p>
                    <span className="text-[10px] text-gray-600 font-bold uppercase">PTS</span>
                </div>
                {data.trade_pnl !== undefined && (
                    <div className={`text-[11px] mt-3 font-black flex items-center gap-2 ${data.trade_pnl >= 0 ? 'text-tv-green' : 'text-tv-red'}`}>
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: data.trade_pnl >= 0 ? '#22ab94' : '#f23645' }} />
                        <span>{data.trade_pnl >= 0 ? '+' : ''}{data.trade_pnl.toFixed(2)}</span>
                        <span className="text-gray-700 font-bold ml-1 uppercase text-[9px] tracking-tighter">Delta_Sync</span>
                    </div>
                )}
            </div>
        );
    }
    return null;
};

const parseContent = (content) => {
    try {
        const data = JSON.parse(content);
        if (data.market_logic) return data.market_logic;
        if (data.action) return `${data.action}: ${data.reason}`;
        if (data.audit_summary) return data.audit_summary;
        return content;
    } catch {
        if (content.includes("Audit |")) return content.split("Audit |")[1].trim();
        return content;
    }
};

export default App;
