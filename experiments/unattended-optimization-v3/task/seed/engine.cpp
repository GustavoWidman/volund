#include "engine.h"
#include <algorithm>
#include <cstdint>
#include <limits>
#include <unordered_map>
#include <vector>

// Baseline: construct a global time index and one time index per stream for
// every invocation; find the two range boundaries and scan matching values.
extern "C" int engine_run(const Event* events, std::size_t event_count,
                          const RangeQuery* queries, std::size_t query_count,
                          RangeResult* results) {
    constexpr std::uint32_t all_streams = std::numeric_limits<std::uint32_t>::max();
    if (event_count > 1000000 || query_count > 4096 ||
        (event_count && !events) || (query_count && (!queries || !results))) return 1;
    for (std::size_t i = 0; i < event_count; ++i)
        if (events[i].stream == all_streams) return 1;
    for (std::size_t i = 0; i < query_count; ++i)
        if (queries[i].lo > queries[i].hi || queries[i].reserved != 0) return 1;
    if (!query_count) return 0;
    try {
        std::vector<Event> global;
        global.reserve(event_count);
        for (std::size_t i = 0; i < event_count; ++i) global.push_back(events[i]);
        std::sort(global.begin(), global.end(), [](const Event& a, const Event& b) {
            return a.timestamp < b.timestamp;
        });
        std::unordered_map<std::uint32_t, std::vector<Event>> by_stream;
        for (const auto& event : global) by_stream[event.stream].push_back(event);
        const auto lower = [](const std::vector<Event>& index, std::uint64_t t) {
            return std::lower_bound(index.begin(), index.end(), t,
                [](const Event& event, std::uint64_t boundary) { return event.timestamp < boundary; });
        };
        for (std::size_t i = 0; i < query_count; ++i) {
            const auto& query = queries[i];
            const std::vector<Event>* index = &global;
            if (query.stream != all_streams) {
                const auto found = by_stream.find(query.stream);
                if (found == by_stream.end()) { results[i] = {}; continue; }
                index = &found->second;
            }
            const auto begin = lower(*index, query.lo);
            const auto end = lower(*index, query.hi);
            RangeResult answer{};
            for (auto it = begin; it != end; ++it) {
                if (answer.count == 0) answer.minimum = answer.maximum = it->value;
                else {
                    answer.minimum = std::min(answer.minimum, it->value);
                    answer.maximum = std::max(answer.maximum, it->value);
                }
                ++answer.count;
                answer.sum += static_cast<std::int64_t>(it->value);
            }
            results[i] = answer;
        }
        return 0;
    } catch (...) {
        return 2;
    }
}
