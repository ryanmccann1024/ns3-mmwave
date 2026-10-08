/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file ns3-command-line-stub.h
 * @brief Minimal stub for ns3/command-line.h so cli-parser.cc compiles without ns-3.
 *
 * Supports the subset ParseCommandLine relies on: AddValue for std::string,
 * int and bool, and Parse of "--name=value" (or "-name=value") arguments.
 * A bool flag given bare ("--rl-mode") is set to true, as in ns-3. Unknown
 * flags are ignored. A malformed int prints an error and exits 1 (ns-3 also
 * rejects it). Deterministic; no help output.
 */
#pragma once

#include <cstdlib>
#include <functional>
#include <iostream>
#include <string>
#include <vector>

namespace ns3
{

class CommandLine
{
  public:
    template <typename T>
    void AddValue(const std::string& name, const std::string& /*help*/, T& value)
    {
        m_items.push_back({name, [&value](const std::string& v, bool hasValue) {
                               Set(value, v, hasValue);
                           }});
    }

    void Parse(int argc, char* argv[])
    {
        for (int i = 1; i < argc; ++i)
        {
            std::string arg = argv[i];
            std::size_t start = arg.find_first_not_of('-');
            if (start == 0 || start == std::string::npos)
            {
                continue;  // positional or bare dashes: ignored
            }
            arg = arg.substr(start);
            std::string name = arg;
            std::string value;
            bool hasValue = false;
            std::size_t eq = arg.find('=');
            if (eq != std::string::npos)
            {
                name = arg.substr(0, eq);
                value = arg.substr(eq + 1);
                hasValue = true;
            }
            for (auto& item : m_items)
            {
                if (item.name == name)
                {
                    item.setter(value, hasValue);
                }
            }
        }
    }

  private:
    struct Item
    {
        std::string name;
        std::function<void(const std::string&, bool)> setter;
    };

    static void Set(std::string& t, const std::string& v, bool) { t = v; }

    static void Set(int& t, const std::string& v, bool)
    {
        try
        {
            std::size_t pos = 0;
            t = std::stoi(v, &pos);
            if (pos != v.size())
            {
                throw std::invalid_argument(v);
            }
        }
        catch (const std::exception&)
        {
            std::cerr << "stub CommandLine: invalid int '" << v << "'\n";
            std::exit(1);
        }
    }

    static void Set(bool& t, const std::string& v, bool hasValue)
    {
        t = !hasValue || v == "true" || v == "1" || v == "t";
    }

    std::vector<Item> m_items;
};

}  // namespace ns3
